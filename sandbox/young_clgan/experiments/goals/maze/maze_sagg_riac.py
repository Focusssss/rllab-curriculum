import os
import random

os.environ['THEANO_FLAGS'] = 'floatX=float32,device=cpu'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import tensorflow as tf
import tflearn
import argparse
import sys
from multiprocessing import cpu_count
from rllab.misc.instrument import run_experiment_lite
from rllab.misc.instrument import VariantGenerator
from sandbox.carlos_snn.autoclone import autoclone
from rllab import config

from sandbox.young_clgan.experiments.goals.maze.maze_sagg_riac_algo import run_task

if __name__ == '__main__':

    fast_mode = False

    parser = argparse.ArgumentParser()
    parser.add_argument('--ec2', '-e', action='store_true', default=False, help="add flag to run in ec2")
    parser.add_argument('--clone', '-c', action='store_true', default=False,
                        help="add flag to copy file and checkout current")
    parser.add_argument('--local_docker', '-d', action='store_true', default=False,
                        help="add flag to run in local dock")
    parser.add_argument('--type', '-t', type=str, default='', help='set instance type')
    parser.add_argument('--price', '-p', type=str, default='', help='set betting price')
    parser.add_argument('--subnet', '-sn', type=str, default='', help='set subnet like us-west-1a')
    parser.add_argument('--name', '-n', type=str, default='', help='set exp prefix name and new file name')
    parser.add_argument('--debug', action='store_true', default=False, help="run code without multiprocessing")
    args = parser.parse_args()

    if args.debug:
        fast_mode = True

    if args.clone:
        autoclone.autoclone(__file__, args)

    # setup ec2
    subnets = [
        'us-east-2a', 'us-east-2b', 'us-east-2c', 'ap-northeast-2a', 'ap-northeast-2c'
    ]
    ec2_instance = args.type if args.type else 'c4.4xlarge' #'m4.10xlarge'
    # configure instan
    info = config.INSTANCE_TYPE_INFO[ec2_instance]
    config.AWS_INSTANCE_TYPE = ec2_instance
    config.AWS_SPOT_PRICE = str(info["price"])
    n_parallel = int(info["vCPU"] / 2)  # make the default 4 if not using ec2
    if args.ec2:
        mode = 'ec2'
    elif args.local_docker:
        mode = 'local_docker'
        n_parallel = cpu_count() if not args.debug else 1
    else:
        mode = 'local'
        n_parallel = cpu_count() if not args.debug else 1
        # n_parallel = multiprocessing.cpu_count()

    exp_prefix = 'goal-sagg-riac-maze11-run1'

    vg = VariantGenerator()
    vg.add('goal_size', [2])  # this is the ultimate goal we care about: getting the pendulum upright
    vg.add('terminal_eps', [0.3])
    vg.add('only_feasible', [True])
    vg.add('maze_id', [0])
    vg.add('goal_range', lambda maze_id: [5] if maze_id==0 else [7])  # this will be used also as bound of the state_space
    vg.add('goal_center', lambda maze_id: [(2, 2)] if maze_id==0 else [(0,0)])
    # goal-algo params
    vg.add('min_reward', [0])
    vg.add('max_reward', [1])
    vg.add('distance_metric', ['L2'])
    vg.add('extend_dist_rew', [True])  # !!!!
    vg.add('use_competence_ratio', [True])  # !!!!
    vg.add('goal_weight', lambda extend_dist_rew: [0] if extend_dist_rew else [1])
    vg.add('persistence', [1])
    if fast_mode:
        vg.add('n_traj', [1])  # only for labeling and plotting (for now, later it will have to be equal to persistence!)
    else:
        vg.add('n_traj', [2])  # only for labeling and plotting (for now, later it will have to be equal to persistence!)
    vg.add('sampling_res', [2])
    vg.add('with_replacement', [False])
    vg.add('smart_init', [True])
    # replay buffer
    vg.add('replay_buffer', [False]) #TODO - try with replay buffer
    vg.add('coll_eps', [0.3])
    vg.add('num_new_goals', [300]) #TODO - change back to 200 when we restore replay buffer
    vg.add('num_old_goals', [0])    #TODO - change back to 100 when we restore replay buffer
    vg.add('add_on_policy', [False]) #TODO - change back to true
    # sampling params
    vg.add('horizon', lambda maze_id: [200] if maze_id == 0 else [500])
    vg.add('outer_iters', [300]) #lambda maze_id: [400] if maze_id == 0 else [10000])
    # policy initialization
    vg.add('output_gain', [1])
    vg.add('policy_init_std', [1])
    vg.add('learn_std', [False])
    vg.add('adaptive_std', [False])
    vg.add('discount', [0.99]) #lambda horizon: [1-1.0/horizon])
    # Oudeyer params
    vg.add('max_goals', [1000])

    vg.add('fast_mode', [fast_mode])
    if args.debug or fast_mode:
        vg.add('pg_batch_size', [20000])
        vg.add('inner_iters', [1])
    else:
        vg.add('pg_batch_size', [20000])
        vg.add('inner_iters', [5])

    # gan configs
    # vg.add('num_labels', [1])  # 1 for single label, 2 for high/low and 3 for learnability
    # vg.add('gan_generator_layers', [[256, 256]])
    # vg.add('gan_discriminator_layers', [[128, 128]])
    # vg.add('gan_noise_size', [4])
    # vg.add('goal_noise_level', [0.5])
    # vg.add('gan_outer_iters', [300])

    if args.ec2:
        vg.add('seed', range(100, 700, 100))
    else:
        vg.add('seed', [100])

    #vg.add('seed', range(0, 1000, 100))

    # # gan_configs
    # vg.add('GAN_batch_size', [128])  # proble with repeated name!!
    # vg.add('GAN_generator_activation', ['relu'])
    # vg.add('GAN_discriminator_activation', ['relu'])
    # vg.add('GAN_generator_optimizer', [tf.train.AdamOptimizer])
    # vg.add('GAN_generator_optimizer_stepSize', [0.001])
    # vg.add('GAN_discriminator_optimizer', [tf.train.AdamOptimizer])
    # vg.add('GAN_discriminator_optimizer_stepSize', [0.001])
    # vg.add('GAN_generator_weight_initializer', [tflearn.initializations.truncated_normal])
    # vg.add('GAN_generator_weight_initializer_stddev', [0.05])
    # vg.add('GAN_discriminator_weight_initializer', [tflearn.initializations.truncated_normal])
    # vg.add('GAN_discriminator_weight_initializer_stddev', [0.02])
    # vg.add('GAN_discriminator_batch_noise_stddev', [1e-2])

    # Launching
    print("\n" + "**********" * 10 + "\nexp_prefix: {}\nvariants: {}".format(exp_prefix, vg.size))
    print('Running on type {}, with price {}, parallel {} on the subnets: '.format(config.AWS_INSTANCE_TYPE,
                                                                                   config.AWS_SPOT_PRICE, n_parallel),
          *subnets)

    for vv in vg.variants():
        if args.debug:
            run_task(vv)

        if mode in ['ec2', 'local_docker']:
            # # choose subnet
            subnet = random.choice(subnets)
            config.AWS_REGION_NAME = subnet[:-1]
            config.AWS_KEY_NAME = config.ALL_REGION_AWS_KEY_NAMES[
                config.AWS_REGION_NAME]
            config.AWS_IMAGE_ID = config.ALL_REGION_AWS_IMAGE_IDS[
                config.AWS_REGION_NAME]
            config.AWS_SECURITY_GROUP_IDS = \
                config.ALL_REGION_AWS_SECURITY_GROUP_IDS[
                    config.AWS_REGION_NAME]
            config.AWS_NETWORK_INTERFACES = [
                dict(
                    SubnetId=config.ALL_SUBNET_INFO[subnet]["SubnetID"],
                    Groups=config.AWS_SECURITY_GROUP_IDS,
                    DeviceIndex=0,
                    AssociatePublicIpAddress=True,
                )
            ]

            run_experiment_lite(
                # use_cloudpickle=False,
                stub_method_call=run_task,
                variant=vv,
                mode=mode,
                # Number of parallel workers for sampling
                n_parallel=n_parallel,
                # Only keep the snapshot parameters for the last iteration
                snapshot_mode="last",
                seed=vv['seed'],
                # plot=True,
                exp_prefix=exp_prefix,
                # exp_name=exp_name,
                # for sync the pkl file also during the training
                sync_s3_pkl=True,
                # sync_s3_png=True,
                sync_s3_html=True,
                # # use this ONLY with ec2 or local_docker!!!
                pre_commands=[
                    'export MPLBACKEND=Agg',
                    'pip install --upgrade pip',
                    'pip install --upgrade -I tensorflow',
                    'pip install git+https://github.com/tflearn/tflearn.git',
                    'pip install dominate',
                    'pip install multiprocessing_on_dill',
                    'pip install scikit-image',
                    'conda install numpy -n rllab3 -y',
                ],
            )
            if mode == 'local_docker':
                sys.exit()
        else:
            # run_task(vv)
            run_experiment_lite(
                # use_cloudpickle=False,
                stub_method_call=run_task,
                variant=vv,
                mode='local',
                n_parallel=n_parallel,
                # Only keep the snapshot parameters for the last iteration
                snapshot_mode="last",
                seed=vv['seed'],
                exp_prefix=exp_prefix,
                # exp_name=exp_name,
            )
