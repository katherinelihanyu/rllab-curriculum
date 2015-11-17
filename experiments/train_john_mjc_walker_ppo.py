import os
os.environ['TENSORFUSE_MODE'] = 'theano'
os.environ['THEANO_FLAGS'] = 'device=cpu'
import rllab.plotter as plotter
plotter.init_worker()
from rllab.sampler import parallel_sampler
parallel_sampler.init_pool(4)
from rllab.vf.mujoco_value_function import MujocoValueFunction
from rllab.mdp.john_mjc import Walker2DMDP
from rllab.algo.ppo import PPO
from rllab.policy.mujoco_policy import MujocoPolicy

if __name__ == '__main__':
    mdp = Walker2DMDP()
    policy = MujocoPolicy(mdp, hidden_sizes=[32, 32])
    vf = MujocoValueFunction()
    algo = PPO(
            exp_name='join_mjc_walker',
            samples_per_itr=5000,
            discount=0.99,
            stepsize=0.01,
            plot=True
    )
    algo.train(mdp, policy, vf)