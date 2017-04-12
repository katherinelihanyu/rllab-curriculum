import multiprocessing
import os
import tempfile
import numpy as np
from collections import OrderedDict

from rllab.sampler.utils import rollout
from rllab.misc import logger

# from sandbox.young_clgan.envs.base import update_env_state_generator
from sandbox.young_clgan.state.selectors import FixedStateSelector, update_env_state_selector


class FunctionWrapper(object):
    """Wrap a function for use with parallelized map.
    """

    def __init__(self, func, *args, **kwargs):
        """Construct the function oject.
        Args:
          func: a top level function, or a picklable callable object.
          *args and **kwargs: Any additional required enviroment data.
        """
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __call__(self, obj):
        return self.func(obj, *self.args, **self.kwargs)


def disable_cuda_initializer(*args, **kwargs):
    import os
    os.environ['THEANO_FLAGS'] = 'device=cpu'
    os.environ['CUDA_VISIBLE_DEVICES'] = ""


def parallel_map(func, iterable_object, num_processes=-1):
    """Parallelized map function based on python process
    Args:
    func: Pickleable callable object that takes one parameter.
    iterable_object: An iterable of elements to map the function on.
    num_processes: Number of process to use. When num_processes is 1,
                   no new process will be created.
    Returns:
    The list resulted in calling the func on all objects in the original list.
    """
    if num_processes == 1:
        return [func(x) for x in iterable_object]
    if num_processes == -1:
        num_processes = min(64, multiprocessing.cpu_count())
    process_pool = multiprocessing.Pool(
        num_processes,
        initializer=disable_cuda_initializer
    )
    results = process_pool.map(func, iterable_object)
    process_pool.close()
    process_pool.join()
    return results


def label_states(states, env, policy, horizon, min_reward, max_reward,
                 old_rewards=None, improvement_threshold=None, n_traj=1, n_processes=-1):
    print("Evaluating states after training")
    mean_rewards = evaluate_states(states, env, policy, horizon, n_traj, n_processes=n_processes)

    print("Computing state labels")
    mean_rewards = mean_rewards.reshape(-1, 1)

    if old_rewards is not None:
        old_rewards = old_rewards.reshape(-1, 1)
        labels = np.hstack(
            [mean_rewards > min_reward, #np.zeros_like(mean_rewards > min_reward, dtype=float), #
             mean_rewards < max_reward,  #np.zeros_like(mean_rewards < max_reward, dtype=float),  #
             mean_rewards - old_rewards >= improvement_threshold
             #np.zeros_like(mean_rewards - old_rewards >= improvement_threshold, dtype=float),
             #
             ]
        ).astype(np.float32)
    else:
        labels = np.hstack(
            [mean_rewards > min_reward, mean_rewards < max_reward]
        ).astype(np.float32)
    return labels


def convert_label(labels):
    """
    :param labels: 3-dim evaluation of the state if they have learnability, 2-dim otherwise
    :return: convert to single integer label and gives associated texts (for plotting). Better if OrderedDict for log!
    """
    # label[0] --> LowRew, label[1] --> HighRew, label[2] --> Learnable ??
    # Put good states last so they will be plotted on top of other states and be most visible.
    classes = OrderedDict({
        # 0: r'Low rewards: $\bar{R}<R_{\min}$',
        0: 'Low rewards',
        # 1: r'High rewards: $\bar{R}>R_{\max}$',
        1: 'High rewards',
        2: 'Good states',
        3: 'Unlearnable',
        4: 'Other',
    })
    new_labels = np.zeros(labels.shape[0], dtype=int)
    new_labels[np.logical_and(labels[:, 0], labels[:, 1])] = 4
    new_labels[labels[:, 0] == False] = 1
    new_labels[labels[:, 1] == False] = 2
    if np.shape(labels)[-1] == 3:
        new_labels[
            np.logical_and(
                np.logical_and(labels[:, 0], labels[:, 1]),
                labels[:, 2] == False
            )
        ] = 3

    return new_labels, classes


def evaluate_states(states, env, policy, horizon, n_traj=1, n_processes=-1):
    evaluate_state_wrapper = FunctionWrapper(
        evaluate_state,
        env=env,
        policy=policy,
        horizon=horizon,
        n_traj=n_traj,
    )
    mean_rewards = parallel_map(
        evaluate_state_wrapper,
        states,
        n_processes
    )
    return np.array(mean_rewards)


def evaluate_state(state, env, policy, horizon, n_traj=1):
    total_rewards = []
    paths = []
    update_env_state_selector(env, FixedStateSelector(state))
    for j in range(n_traj):
        paths.append(rollout(env, policy, horizon))
        total_rewards.append(
            np.sum(paths[-1]['rewards'])
        )
    mean_reward = np.mean(total_rewards)
    # if 0 < mean_reward < 300:
    #     # extra_paths = []
    #     # for i in range(2):
    #     #     extra_paths.append(rollout(env, policy, horizon, animated=True))
    #     # print("Dists: ", [np.min(path['env_infos']['distance']) for path in extra_paths])
    #     min_dists = [np.min(path['env_infos']['distance']) for path in paths]
    #     traj_lens = [np.shape(path['rewards'])[0] for path in paths]
    #     print("State: {}, Mean reward: {}, rewards: {}, traj_len: {}, min_dists: {}".format(state, mean_reward, total_rewards, traj_lens, min_dists))

    return mean_reward


def evaluate_state_env(env, policy, horizon, n_states=10, n_traj=1, **kwargs):
    paths = [rollout(env=env, agent=policy, max_path_length=horizon) for _ in range(n_states)]
    env.log_diagnostics(paths, n_traj=n_traj, **kwargs)