"""
Variational DDPG (online, consevative)

Continue exp-003.
* smaller alpha to encourage faster learning
* fix policy_learning_rate = 1e-3 since it doesn't make a difference
* use freeze_samples = True since it doesn't make a difference
* snapshot_gap: 10 -> 50
* plot exp(Q / alpha) instead of Q, since that makes it easier to imagine the
    prob density
"""
# imports -----------------------------------------------------
import tensorflow as tf
import joblib
from rllab.envs.normalized_env import normalize
from rllab.exploration_strategies.ou_strategy import OUStrategy
from sandbox.rocky.tf.envs.base import TfEnv
from sandbox.haoran.myscripts.envs import EnvChooser
from sandbox.tuomas.mddpg.kernels.gaussian_kernel import \
    SimpleAdaptiveDiagonalGaussianKernel
from sandbox.tuomas.mddpg.critics.nn_qfunction import FeedForwardCritic
from sandbox.tuomas.mddpg.policies.stochastic_policy import StochasticNNPolicy
from sandbox.tuomas.mddpg.algos.vddpg import VDDPG

""" others """
from sandbox.haoran.myscripts.myutilities import get_time_stamp
from sandbox.haoran.ec2_info import instance_info, subnet_info
from rllab import config
from rllab.misc.instrument import stub, run_experiment_lite
import sys,os
import copy
import numpy as np

stub(globals())

from rllab.misc.instrument import VariantGenerator, variant

# exp setup --------------------------------------------------------
exp_index = os.path.basename(__file__).split('.')[0] # exp_xxx
exp_prefix = "mddpg/vddpg/" + exp_index
mode = "ec2"
subnet = "us-west-1b"
config.DOCKER_IMAGE = "tsukuyomi2044/rllab3" # needs psutils
config.AWS_IMAGE_ID = "ami-85d181e5" # with docker already pulled

n_task_per_instance = 5
n_parallel = 1 # only for local exp
snapshot_mode = "gap"
snapshot_gap = 50
plot = True
sync_s3_pkl = True

# variant params ---------------------------------------------------
class VG(VariantGenerator):
    @variant
    def zzseed(self):
        return [0, 100, 200, 300, 400]

    @variant
    def env_name(self):
        return [
            "swimmer_undirected"
        ]
    @variant
    def K(self):
        return [64]

    @variant
    def alpha(self):
        return [0.01, 0.025, 0.05]

    @variant
    def max_path_length(self):
        return [500]

    @variant
    def q_target_type(self):
        return [
            "max"
        ]
    @variant
    def ou_sigma(self):
        return [0.3]

    @variant
    def scale_reward(self):
        return [1.]

    @variant
    def freeze_samples(self):
        return [True]

    @variant
    def qf_learning_rate(self):
        return [1e-3]

    @variant
    def policy_learning_rate(self):
        return [1e-3]

    @variant
    def svgd_type(self):
        return ["pre-action", "scaled-tanh", "action"]

    @variant
    def ec2_instance(self):
        return ["c4.4xlarge"]

variants = VG().variants()
batch_tasks = []
print("#Experiments: %d" % len(variants))
for v in variants:
    # non-variant params -----------------------------------
    # >>>>>>
    # algo
    seed=v["zzseed"]
    env_name = v["env_name"]
    K = v["K"]
    ec2_instance = v["ec2_instance"]

    shared_alg_kwargs = dict(
        alpha=v["alpha"],
        max_path_length=v["max_path_length"],
        q_target_type = v["q_target_type"],
        scale_reward=v["scale_reward"],
        qf_learning_rate=v["qf_learning_rate"],
        policy_learning_rate=v["policy_learning_rate"],
    )
    if v["svgd_type"] != "scaled-tanh":
        shared_alg_kwargs["svgd_target"] = v["svgd_type"]
        output_scale = 1.0
    else:
        shared_alg_kwargs["svgd_target"] = "action"
        output_scale = 2.0
    if mode == "local_test" or mode == "local_docker_test":
        alg_kwargs = dict(
            epoch_length=10,
            min_pool_size=20000,
                # beware that the algo doesn't finish an epoch
                # until it finishes one path
            n_eval_paths=1,
            n_epochs=5,
        )
    else:
        alg_kwargs = dict(
            epoch_length=1000,
            n_epochs=1000,
            eval_samples=100,
            n_eval_paths=5,
        )
    alg_kwargs.update(shared_alg_kwargs)
    if env_name == "hopper":
        env_kwargs = {
            "alive_coeff": 0.5
        }
    elif env_name == "swimmer_undirected":
        env_kwargs = {
            "random_init_state": False
        }
    else:
        env_kwargs = {}

    # other exp setup --------------------------------------
    exp_name = "{exp_index}_{time}_{env_name}".format(
        exp_index=exp_index,
        time=get_time_stamp(),
        env_name=env_name
    )
    if ("ec2" in mode) and (len(exp_name) > 64):
        print("Should not use experiment name with length %d > 64.\nThe experiment name is %s.\n Exit now."%(len(exp_name),exp_name))
        sys.exit(1)

    if "local_docker" in mode:
        actual_mode = "local_docker"
    elif "local" in mode:
        actual_mode = "local"
    elif "ec2" in mode:
        actual_mode = "ec2"
        # configure instance
        info = instance_info[ec2_instance]
        config.AWS_INSTANCE_TYPE = ec2_instance
        config.AWS_SPOT_PRICE = str(info["price"])
        n_parallel = int(info["vCPU"] /2)

        # choose subnet
        config.AWS_NETWORK_INTERFACES = [
            dict(
                SubnetId=subnet_info[subnet]["SubnetID"],
                Groups=subnet_info[subnet]["Groups"],
                DeviceIndex=0,
                AssociatePublicIpAddress=True,
            )
        ]
    elif "kube" in mode:
        actual_mode = "lab_kube"
        info = instance_info[ec2_instance]
        n_parallel = int(info["vCPU"] /2)

        config.KUBE_DEFAULT_RESOURCES = {
            "requests": {
                "cpu": int(info["vCPU"]*0.75)
            }
        }
        config.KUBE_DEFAULT_NODE_SELECTOR = {
            "aws/type": ec2_instance
        }
        exp_prefix = exp_prefix.replace('/','-') # otherwise kube rejects
    else:
        raise NotImplementedError

    # construct objects ----------------------------------
    env_chooser = EnvChooser()
    env = TfEnv(normalize(
        env_chooser.choose_env(env_name,**env_kwargs),
        clip=(not (v["svgd_type"] == "scaled-tanh")),
    ))

    qf = FeedForwardCritic(
        "critic",
        env.observation_space.flat_dim,
        env.action_space.flat_dim,
        observation_hidden_sizes=(),
        embedded_hidden_sizes=(100, 100),
    )
    q_prior = None
    es = OUStrategy(
        env_spec=env.spec,
        mu=0,
        theta=0.15,
        sigma=v["ou_sigma"],
        clip=(not (v["svgd_type"] == "scaled-tanh")),
    )
    policy = StochasticNNPolicy(
        scope_name="actor",
        observation_dim=env.observation_space.flat_dim,
        action_dim=env.action_space.flat_dim,
        sample_dim=2,
        freeze_samples=v["freeze_samples"],
        K=K,
        output_nonlinearity=tf.nn.tanh,
        hidden_dims=(100, 100),
        W_initializer=None,
        output_scale=output_scale,
    )
    kernel = SimpleAdaptiveDiagonalGaussianKernel(
        "kernel",
        dim=env.action_space.flat_dim,
    )
    algorithm = VDDPG(
        env=env,
        exploration_strategy=es,
        policy=policy,
        kernel=kernel,
        qf=qf,
        q_prior=q_prior,
        K=K,
        **alg_kwargs
    )

    # run -----------------------------------------------------------
    print(v)
    batch_tasks.append(
        dict(
            stub_method_call=algorithm.train(),
            exp_name=exp_name,
            seed=seed,
            snapshot_mode=snapshot_mode,
            snapshot_gap=snapshot_gap,
            variant=v,
            plot=plot,
            n_parallel=n_parallel,
        )
    )
    if len(batch_tasks) >= n_task_per_instance:
        run_experiment_lite(
            batch_tasks=batch_tasks,
            exp_prefix=exp_prefix,
            mode=actual_mode,
            sync_s3_pkl=True,
            sync_s3_log=True,
            sync_s3_png=True,
            sync_log_on_termination=True,
            sync_all_data_node_to_s3=True,
            terminate_machine=True,
        )
        batch_tasks = []
        if "test" in mode:
            sys.exit(0)

if ("local" not in mode) and ("test" not in mode):
    os.system("chmod 444 %s"%(__file__))
