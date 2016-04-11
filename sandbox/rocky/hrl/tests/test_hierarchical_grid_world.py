from __future__ import print_function
from __future__ import absolute_import
import numpy as np
from rllab.spaces.discrete import Discrete
from rllab.spaces.product import Product
# from nose2.tools import

from nose2.tools import such

with such.A("expand_grid") as it:
    @it.should("work")
    def test_expand_grid():
        from sandbox.rocky.hrl.hierarchical_grid_world_env import expand_grid
        high_grid = [
            "SFF",
            "FWH",
            "FFG"
        ]
        low_grid = [
            "SFF",
            "FFF",
            "FFG"
        ]

        total_grid = expand_grid(high_grid, low_grid)
        it.assertEqual(total_grid.shape, (9, 9))
        it.assertEqual(np.sum(total_grid == 'F'), 8 + 9 + 9 + 9 + 9 + 9 + 8)
        it.assertEqual(np.sum(total_grid == 'S'), 1)
        it.assertEqual(np.sum(total_grid == 'G'), 1)
        it.assertEqual(np.sum(total_grid == 'W'), 9)
        it.assertEqual(np.sum(total_grid == 'H'), 9)
        it.assertEqual(total_grid[0, 0], 'S')
        it.assertEqual(total_grid[8, 8], 'G')

it.createTests(globals())

with such.A("hierarchical grid world") as it:
    @it.should("work")
    def test_hierarchical_grid_world():
        from sandbox.rocky.hrl.hierarchical_grid_world_env import HierarchicalGridWorldEnv
        from rllab.envs.grid_world_env import GridWorldEnv
        high_grid = [
            "SFF",
            "FWH",
            "FFG"
        ]
        low_grid = [
            "SFF",
            "FFF",
            "FFG"
        ]

        hier_grid_world = HierarchicalGridWorldEnv(high_grid, low_grid)
        it.assertEqual(hier_grid_world.observation_space, Product(Discrete(9), Discrete(9)))
        it.assertEqual(hier_grid_world.action_space, Discrete(4))
        state = hier_grid_world.reset()
        it.assertEqual(state, (0, 0))
        right_action = GridWorldEnv.action_from_direction("right")
        it.assertEqual(hier_grid_world.step(right_action)[0], (0, 1))
        it.assertEqual(hier_grid_world.step(right_action)[0], (0, 2))
        it.assertEqual(hier_grid_world.step(right_action)[0], (1, 0))

it.createTests(globals())