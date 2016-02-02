require_relative '../../rocky/utils'

itrs = 500# 100
batch_size = 50000
horizon = 500
discount = 0.99
seeds = (1..5).map do |i| i ** 2 * 5 + 23 end

mdps = []
# basics
# mdps << "box2d.cartpole_mdp"
# mdps << "box2d.mountain_car_mdp"
mdps << "box2d.cartpole_swingup_mdp"
# # mdps << "box2d.double_pendulum_mdp"
# # mdps << "box2d.car_parking_mdp"
mdps << "mujoco_1_22.inverted_double_pendulum_mdp"
# 
# # loco
mdps << "mujoco_1_22.swimmer_mdp"
# mdps << "mujoco_1_22.hopper_mdp"
# mdps << "mujoco_1_22.walker2d_mdp"
# mdps << "mujoco_1_22.half_cheetah_mdp"
mdps << "mujoco_1_22.ant_mdp"
# mdps << "mujoco_1_22.simple_humanoid_mdp"
# mdps << "mujoco_1_22.humanoid_mdp"

algos = []

# # cem
[0.05, 0.5].each do |best_frac|
  [0.01, 0.1, 1, 10].each do |extra_std|
    [itrs*0.3, itrs*0.5, itrs*0.8].each do |extra_decay_time|
      algos << {
        _name: "cem",
        # n_samples: (batch_size*1.0/horizon).to_i,
        best_frac: best_frac,
        extra_std: extra_std,
        extra_decay_time: extra_decay_time.to_i,
      }
    end
  end
end


hss = []
hss << [100, 50, 25]

inc = 9999
hss.each do |hidden_sizes|
  seeds.each do |seed|
    mdps.each do |mdp|
      algos.each do |algo|
        exp_name = "restart_search_0_#{inc = inc + 1}_#{seed}_#{mdp}_#{algo[:_name]}"
        params = {
          mdp: {
            _name: mdp,
          },
          normalize_mdp: true,
          policy: {
            _name: "mean_std_nn_policy",
            hidden_sizes: hidden_sizes,
          },
          baseline: {
            _name: "linear_feature_baseline",
          },
          exp_name: exp_name,
          algo: {
            whole_paths: true,
            max_path_length: horizon,
            n_itr: itrs,
            discount: discount,
            # plot: true,
          }.merge(algo).merge(algo[:_name] == "cem" ? {} : {batch_size: batch_size}),
          n_parallel: 8,
          snapshot_mode: "last",
          seed: seed,
          # plot: true,
        }
        command = to_command(params)
        # puts command
        # system(command)
        # command = "LD_LIBRARY_PATH=/root/workspace/rllab/private/mujoco/binaries/1_22/linux #{command}"
  # --device /dev/nvidia0:/dev/nvidia0 \
  # --device /dev/nvidiactl:/dev/nvidiactl \
  # --device /dev/nvidia-uvm:/dev/nvidia-uvm \
        dockerified = """docker run \
  -v ~/.bash_history:/root/.bash_history \
  -v /slave/theano_cache_docker:/root/.theano \
  -v /slave/theanorc:/root/.theanorc \
  -v ~/.vim:/root/.vim \
  -v /slave/gitconfig:/root/.gitconfig \
  -v ~/.vimrc:/root/.vimrc \
  -v /slave/dockerfiles/ssh:/root/.ssh \
  -v /slave/jupyter:/root/.jupyter \
  -v /home/ubuntu/data:/root/workspace/data \
  -v /slave/workspace:/root/workspace \
  -v `pwd`/rllab:/root/workspace/rllab \
  --env LD_LIBRARY_PATH=/root/workspace/rllab/private/mujoco/binaries/1_22/linux:/usr/local/cuda/lib64 \
  dementrock/starcluster:0131 #{command}"""
        # puts dockerified
        # system(dockerified)
        fname = "#{exp_name}.sh"
        f = File.open(fname, "w")
        f.puts dockerified
        f.close
        system("chmod +x " + fname)
        system("qsub -V -b n -l mem_free=8G,h_vmem=14G -r y -cwd " + fname)
        # if mdp =~ /parking/ or mdp =~ /\.double/
        #     puts `~/qs.sh | grep #{exp_name} | /usr/local/sbin/kill.rb`
        # end
      end
    end
  end
end

