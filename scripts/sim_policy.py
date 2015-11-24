import os
import numpy as np
from rllab.policy.mujoco_policy import MujocoPolicy
from rllab.mdp.john_mjc2 import SwimmerMDP#.ant_mdp import AntMDP
#from rllab.mdp.igor_mjc import AcrobotMDP
from rllab.sampler.utils import rollout

import sys
import argparse


print 'reading data'
data = np.load('itr_014.npz')
print 'read data'

params = data['cur_policy_params']
print params.shape
mdp = SwimmerMDP()
policy = MujocoPolicy(mdp, hidden_sizes=[32, 32])#30,30])
print policy.get_param_values().shape
policy.set_param_values(params)
# zero out the variance
#policy.log_std_vars[0].set_value(np.ones_like(policy.log_std_vars[0].get_value()) * -100)
#cur_params = policy.get_param_values()
result = rollout(mdp, policy, max_length=1000, animated=True)#mdp.demo_policy(policy)
#import ipdb; ipdb.set_trace()

