from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.envs.box2d.cartpole_env import CartpoleEnv
from rllab.envs.normalized_env import normalize
from sandbox.rocky.chainer.algos.trpo import TRPO
from sandbox.rocky.chainer.policies.gaussian_mlp_policy import GaussianMLPPolicy

if __name__ == "__main__":
    env = normalize(CartpoleEnv())

    policy = GaussianMLPPolicy(
        env_spec=env.spec,
        # The neural network policy should have two hidden layers, each with 32 hidden units.
        hidden_sizes=(32, 32)
    )

    baseline = LinearFeatureBaseline(env_spec=env.spec)

    algo = TRPO(
        env=env,
        policy=policy,
        baseline=baseline,
        batch_size=1000,
        max_path_length=100,
        n_itr=40,
        discount=0.99,
        step_size=0.01,
    )
    algo.train()
