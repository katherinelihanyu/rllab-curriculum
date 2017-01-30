# from rllab.sampler import parallel_sampler
# parallel_sampler.initialize(n_parallel=2)
# parallel_sampler.set_seed(1)

from rllab.algos.trpo import TRPO
from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.envs.normalized_env import normalize
from rllab.misc.instrument import stub, run_experiment_lite
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy
import math

# from rllab.envs.mujoco.swimmer_env import SwimmerEnv
# from sandbox.carlos_snn.envs.mujoco.snake_env import SnakeEnv
from sandbox.carlos_snn.envs.mujoco.maze.snake_maze_env import SnakeMazeEnv
# from rllab.envs.mujoco.maze.ant_maze_env import AntMazeEnv
from sandbox.carlos_snn.envs.mujoco.swimmer_env import SwimmerEnv
# from rllab.envs.mujoco.maze.swimmer_maze_env import SwimmerMazeEnv
# from sandbox.carlos_snn.envs.mujoco.maze.swimmer_maze_env import SwimmerMazeEnv
from sandbox.carlos_snn.envs.mujoco.gather.gather_env import GatherEnv

stub(globals())

# env = normalize(SwimmerEnv(ego_obs=True))
# env = normalize(SnakeMazeEnv(maze_id=3, sensor_span=2*math.pi))  #, ego_obs=True))
# env = normalize(SnakeMazeEnv(maze_id=3, sensor_span=2*math.pi, ego_obs=True))
# env = SwimmerMazeEnv(sensor_span=math.pi*2, ctrl_cost_coeff=1)

for time_step_agg in [10, 50, 100]:

    for activity_range in [6, 10, 15]:
        env = normalize(SnakeMazeEnv(maze_id=0, sensor_span=math.pi * 2, ego_obs=True))

        policy = GaussianMLPPolicy(
            env_spec=env.spec,
            # The neural network policy should have two hidden layers, each with 32 hidden units.
            hidden_sizes=(64, 64)
        )

        baseline = LinearFeatureBaseline(env_spec=env.spec)

        algo = TRPO(
            env=env,
            policy=policy,
            baseline=baseline,
            batch_size=50000,
            max_path_length=500,
            n_itr=200,
            discount=0.99,
            step_size=0.01,
            # Uncomment both lines (this and the plot parameter below) to enable plotting
            # plot=True,
        )

        for s in range(0, 150, 10):
            run_experiment_lite(
                algo.train(),
                # where to launch the instances
                mode='ec2',
                # Number of parallel workers for sampling
                n_parallel=4,
                # Only keep the snapshot parameters for the last iteration
                snapshot_mode="last",
                ## !!!
                sync_s3_pkl=True,
                sync_s3_png=True,
                # Specifies the seed for the experiment. If this is not provided, a random seed
                # will be used
                seed=s,
                # plot=True,
                exp_prefix='egoSwimmer-trpo',
                exp_name='egoSwimmer-trpo-50kBs-200itr-500pl-{}'.format(s)
            )

            # print("about to train the algo")
            # algo.train()
