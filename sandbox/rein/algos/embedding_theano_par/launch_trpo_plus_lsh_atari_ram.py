import itertools
import os
import lasagne

from rllab.misc.instrument import stub, run_experiment_lite
from sandbox.rein.algos.embedding_theano.theano_atari import AtariEnv
from rllab.policies.categorical_mlp_policy import CategoricalMLPPolicy
from sandbox.rein.algos.embedding_theano_par.trpo_plus_lsh import ParallelTRPOPlusLSH
from sandbox.rein.dynamics_models.bnn.conv_bnn_count import ConvBNNVIME
from sandbox.rein.algos.embedding_theano_par.linear_feature_baseline import ParallelLinearFeatureBaseline
from rllab.envs.env_spec import EnvSpec
from rllab.spaces.box import Box

os.environ["THEANO_FLAGS"] = "device=gpu"

stub(globals())

n_seq_frames = 1
n_parallel = 2
model_batch_size = 32
exp_prefix = 'trpo-par-rndconv-a'
seeds = [0, 1, 2]
etas = [0.001]
mdps = [AtariEnv(game='freeway', obs_type="ram+image", frame_skip=4),
        AtariEnv(game='breakout', obs_type="ram+image", frame_skip=4),
        AtariEnv(game='frostbite', obs_type="ram+image", frame_skip=4),
        AtariEnv(game='montezuma_revenge', obs_type="ram+image", frame_skip=4)]
trpo_batch_size = 5000
max_path_length = 450
dropout = False
batch_norm = False

param_cart_product = itertools.product(
    mdps, etas, seeds
)

for mdp, eta, seed in param_cart_product:
    mdp_spec = EnvSpec(
        observation_space=Box(low=-1, high=1, shape=(1, 128)),
        action_space=mdp.spec.action_space
    )

    policy = CategoricalMLPPolicy(
        env_spec=mdp_spec,
        hidden_sizes=(128, 128),
    )
    baseline = ParallelLinearFeatureBaseline(env_spec=mdp_spec)

    env_spec = EnvSpec(
        observation_space=Box(low=-1, high=1, shape=(n_seq_frames, 52, 52)),
        action_space=mdp.spec.action_space
    )

    autoenc = ConvBNNVIME(
        state_dim=env_spec.observation_space.shape,
        action_dim=(env_spec.action_space.flat_dim,),
        reward_dim=(1,),
        layers_disc=[
            dict(name='convolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(0, 0),
                 batch_norm=batch_norm,
                 nonlinearity=lasagne.nonlinearities.linear,
                 dropout=False,
                 deterministic=True),
            dict(name='convolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(1, 1),
                 batch_norm=batch_norm,
                 nonlinearity=lasagne.nonlinearities.linear,
                 dropout=False,
                 deterministic=True),
            dict(name='convolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(2, 2),
                 batch_norm=batch_norm,
                 nonlinearity=lasagne.nonlinearities.linear,
                 dropout=False,
                 deterministic=True),
            dict(name='reshape',
                 shape=([0], -1)),
            dict(name='gaussian',
                 n_units=512,
                 matrix_variate_gaussian=False,
                 nonlinearity=lasagne.nonlinearities.linear,
                 batch_norm=batch_norm,
                 dropout=dropout,
                 deterministic=True),
            dict(name='discrete_embedding',
                 n_units=4096,
                 batch_norm=batch_norm,
                 deterministic=True),
            dict(name='gaussian',
                 n_units=512,
                 matrix_variate_gaussian=False,
                 nonlinearity=lasagne.nonlinearities.rectify,
                 batch_norm=batch_norm,
                 dropout=dropout,
                 deterministic=True),
            dict(name='gaussian',
                 n_units=2400,
                 matrix_variate_gaussian=False,
                 nonlinearity=lasagne.nonlinearities.rectify,
                 batch_norm=batch_norm,
                 dropout=False,
                 deterministic=True),
            dict(name='reshape',
                 shape=([0], 96, 5, 5)),
            dict(name='deconvolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(2, 2),
                 nonlinearity=lasagne.nonlinearities.rectify,
                 batch_norm=batch_norm,
                 dropout=False,
                 deterministic=True),
            dict(name='deconvolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(0, 0),
                 nonlinearity=lasagne.nonlinearities.rectify,
                 batch_norm=batch_norm,
                 dropout=False,
                 deterministic=True),
            dict(name='deconvolution',
                 n_filters=96,
                 filter_size=(6, 6),
                 stride=(2, 2),
                 pad=(0, 0),
                 nonlinearity=lasagne.nonlinearities.linear,
                 batch_norm=True,
                 dropout=False,
                 deterministic=True),
        ],
        n_batches=1,
        trans_func=lasagne.nonlinearities.rectify,
        out_func=lasagne.nonlinearities.linear,
        batch_size=model_batch_size,
        n_samples=1,
        num_train_samples=1,
        prior_sd=0.05,
        second_order_update=False,
        learning_rate=0.0003,
        surprise_type=ConvBNNVIME.SurpriseType.VAR,
        update_prior=False,
        update_likelihood_sd=False,
        output_type=ConvBNNVIME.OutputType.CLASSIFICATION,
        num_classes=64,
        likelihood_sd_init=0.1,
        disable_variance=False,
        ind_softmax=True,
        num_seq_inputs=1,
        label_smoothing=0.003,
        # Disable prediction of rewards and intake of actions, act as actual autoenc
        disable_act_rew_paths=True,
        # --
        # Count settings
        # Put penalty for being at 0.5 in sigmoid postactivations.
        binary_penalty=True,
    )

    algo = ParallelTRPOPlusLSH(
        model=autoenc,
        discount=0.995,
        env=mdp,
        policy=policy,
        baseline=baseline,
        batch_size=trpo_batch_size,
        max_path_length=max_path_length,
        n_parallel=n_parallel,
        n_itr=500,
        step_size=0.01,
        optimizer_args=dict(
            num_slices=50,
            subsample_factor=0.1,
        ),
        n_seq_frames=n_seq_frames,
        # --
        # Count settings
        model_pool_args=dict(
            size=1000000,
            min_size=model_batch_size,
            batch_size=model_batch_size,
            subsample_factor=0.3,
            fill_before_subsampling=False,
        ),
        eta=eta,
        train_model=False,
        train_model_freq=5,
        continuous_embedding=False,
        model_embedding=True,
        sim_hash_args=dict(
            dim_key=256,
            bucket_sizes=None,  # [15485867, 15485917, 15485927, 15485933, 15485941, 15485959],
            parallel=False,
        )
    )

    run_experiment_lite(
        algo.train(),
        exp_prefix=exp_prefix,
        n_parallel=n_parallel,
        snapshot_mode="last",
        seed=seed,
        mode="local",
        dry=False,
        use_gpu=False,
        script="sandbox/rein/algos/embedding_theano/run_experiment_lite_ram_img.py",
        # Sync ever 1h.
        periodic_sync_interval=60 * 60,
        sync_all_data_node_to_s3=True
    )
