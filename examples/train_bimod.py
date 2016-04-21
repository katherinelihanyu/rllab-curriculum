from rllab.algos.ppo import PPO
from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from examples.bimod_env import BimodEnv
from rllab.envs.normalized_env import normalize
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy
from rllab.misc.instrument import stub, run_experiment_lite

env = normalize(BimodEnv())
policy = GaussianMLPPolicy(
    env_spec=env.spec,
)
baseline = LinearFeatureBaseline(env_spec=env.spec)
algo = PPO(
    env=env,
    policy=policy,
    baseline=baseline,
    batch_size=400,
    whole_paths=True,
    max_path_length=100,
    n_itr=40,
    discount=0.99,
    step_size=0.01,
)


run_experiment_lite(
    stub_method_call=algo.train(),
    # Number of parallel workers for sampling
    n_parallel=1,
    # Only keep the snapshot parameters for the last iteration
    snapshot_mode="last",
    # Specifies the seed for the experiment. If this is not provided, a random seed
    # will be used
    seed=1,
    # plot=True,
    # Save to data/local/exp_name_timestamp
    exp_prefix='ppo_try',
)