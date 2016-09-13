


from rllab.misc.instrument import run_experiment_lite, stub
from sandbox.pchen.InfoGAN.infogan.algos.semi_vae import SemiVAE
from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import AdamaxOptimizer
from sandbox.pchen.InfoGAN.infogan.misc.distributions import Uniform, Categorical, Gaussian, MeanBernoulli, Bernoulli, Mixture, AR

import os
from sandbox.pchen.InfoGAN.infogan.misc.datasets import MnistDataset, FaceDataset, BinarizedMnistDataset, \
    ResamplingBinarizedMnistDataset
from sandbox.pchen.InfoGAN.infogan.models.regularized_helmholtz_machine import RegularizedHelmholtzMachine
from sandbox.pchen.InfoGAN.infogan.algos.vae import VAE
from sandbox.pchen.InfoGAN.infogan.misc.utils import mkdir_p, set_seed, skip_if_exception
import dateutil
import dateutil.tz
import datetime
import numpy as np

now = datetime.datetime.now(dateutil.tz.tzlocal())
timestamp = ""#now.strftime('%Y_%m_%d_%H_%M_%S')

root_log_dir = "logs/res_comparison_wn_adamax"
root_checkpoint_dir = "ckt/mnist_vae"
batch_size = 128
updates_per_epoch = 100
max_epoch = 85

stub(globals())

from rllab.misc.instrument import VariantGenerator, variant

# pa_mnist_lr_0.0001_min_kl_0.05_mix_std_0.8_monte_carlo_kl_True_nm_10_seed_42_zdim_64
class VG(VariantGenerator):
    @variant
    def lr(self):
        # yield 0.0005#
        # yield
        # return np.arange(1, 11) * 1e-4
        # return [0.0001, 0.0005, 0.001]
        return [0.002, 0.0001] #0.001]

    @variant
    def seed(self):
        return [42, ]
        # return [123124234]

    @variant(hide=True)
    def monte_carlo_kl(self):
        return [True, ]

    @variant
    def zdim(self):
        return [32, ]#[12, 32]

    @variant(hide=True)
    def min_kl(self):
        return [0.01, ] #0.05, 0.1]
    #
    @variant
    def nar(self):
        # return [0,]#2,4]
        # return [2,]#2,4]
        # return [0,1,]#4]
        return [0,]

    @variant
    def nr(self, nar):
        if nar == 0:
            return [1]
        else:
            return [10, ]

    # @variant
    # def nm(self):
    #     return [10, ]
    #     return [5, 10, 20]

    # @variant
    # def pr(self):
    #     return [True, False]

    @variant(hide=True)
    def network(self):
        # yield "large_conv"
        # yield "small_conv"
        # yield "deep_mlp"
        # yield "mlp"
        # yield "resv1_k3"
        # yield "conv1_k5"
        # yield "small_res"
        # yield "small_res_small_kern"
        # yield "resv1_k3_pixel_bias"
        # yield "resv1_k3_pixel_bias_filters_ratio"
        # yield "resv1_k3_pixel_bias_filters_ratio"
        yield "small_conv"

    @variant()
    def keep_prob(self, network):
            return [1., 0.9, 0.7, 0.5]

    # @variant()
    # def base_filters(self, network):
    #     if network == "resv1_k3_pixel_bias_filters_ratio":
    #         return [2,4]
    #     else:
    #         return [0]
    #
    # @variant()
    # def fc_size(self, network):
    #     if network == "resv1_k3_pixel_bias_filters_ratio":
    #         return [450, 250, 150]
    #     else:
    #         return [0]

    @variant(hide=True)
    def wnorm(self):
        return [True, ]

    @variant(hide=True)
    def ar_wnorm(self):
        return [True, ]

    @variant(hide=True)
    def k(self):
        return [8, ]

    @variant(hide=False)
    def npl(self):
        return [5000]
        # return [5, 10, 100, 1000]

    @variant(hide=False)
    def sup_bs(self, npl):
        return [100]
        # return [
        #     bs for bs in [10, 100] if bs <= npl
        # ]

    @variant(hide=False)
    def sup_coeff(self, npl):
        return [
            1.,
            ]

    @variant(hide=False)
    def semi_arch(self, ):
        return [
            [60],
            # [60, 30,],
        ]

    # @variant(hide=False)
    # def dropout_keep_prob(self, ):
    #     return [
    #         1.,
    #         0.5,
    #         # 0.3,
    #     ]

    @variant(hide=False)
    def delay_until(self, ):
        return [
            0,
            # 100,
            # 200,
        ]

    @variant(hide=False)
    def use_mean(self, ):
        return [
            True, # False,
        ]

vg = VG()

variants = vg.variants(randomized=True)

print(len(variants))

for v in variants[:]:

    # with skip_if_exception():

        zdim = v["zdim"]
        import tensorflow as tf
        tf.reset_default_graph()
        exp_name = "pa_mnist_%s" % (vg.to_name_suffix(v))

        print("Exp name: %s" % exp_name)

        # set_seed(v["seed"])

        dataset = ResamplingBinarizedMnistDataset(labels_per_class=v["npl"])
        # dataset = MnistDataset()

        dist = Gaussian(zdim)
        for _ in range(v["nar"]):
            dist = AR(zdim, dist, neuron_ratio=v["nr"], data_init_wnorm=v["ar_wnorm"])

        latent_spec = [
            # (Gaussian(128), False),
            # (Categorical(10), True),
            (
                # Mixture(
                #     [
                #         (
                #             Gaussian(
                #                 zdim,
                #                 # prior_mean=np.concatenate([[2.*((i>>j)%2) for j in xrange(4)], np.random.normal(scale=v["mix_std"], size=zdim-4)]),
                #                 prior_mean=np.concatenate([np.random.normal(scale=v["mix_std"], size=zdim)]),
                #                 init_prior_mean=np.zeros(zdim),
                #                 prior_trainable=True,
                #             ),
                #             1. / nm
                #         ) for i in xrange(nm)
                #     ]
                # )
                dist
                ,
                False
            ),
        ]

        model = RegularizedHelmholtzMachine(
            output_dist=MeanBernoulli(dataset.image_dim),
            latent_spec=latent_spec,
            batch_size=batch_size,
            image_shape=dataset.image_shape,
            network_type=v["network"],
            network_args=dict(
                # enc_fc_keep_prob=v["enc_fc_keepprob"],
                # enc_res_keep_prob=v["enc_res_keepprob"],
                keep_prob=v["keep_prob"],
            ),
            inference_dist=Gaussian(
                zdim,
            ),
            wnorm=v["wnorm"],
        )

        algo = SemiVAE(
            model=model,
            dataset=dataset,
            batch_size=batch_size,
            sup_batch_size=v["sup_bs"],
            sup_coeff=v["sup_coeff"],
            exp_name=exp_name,
            max_epoch=max_epoch,
            updates_per_epoch=updates_per_epoch,
            optimizer_cls=AdamaxOptimizer,
            optimizer_args=dict(
                learning_rate=v["lr"]
            ),
            monte_carlo_kl=v["monte_carlo_kl"],
            min_kl=v["min_kl"],
            k=v["k"],
            hidden_units=v["semi_arch"],
            delay_until=v["delay_until"],
            vali_eval_interval=500,
            dropout_keep_prob=v["keep_prob"],
            vae_off=True,
            use_mean=v["use_mean"],
        )

        run_experiment_lite(
            algo.train(),
            exp_prefix="0816_pure_semi_arch_dropout_m",
            seed=v["seed"],
            variant=v,
            # mode="local",
            mode="lab_kube",
            n_parallel=0,
            use_gpu=True,
        )

