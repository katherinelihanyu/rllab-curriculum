import tensorfuse.tensor as TT
from rllab.misc import logger, autoargs
from rllab.misc.overrides import overrides
from rllab.misc.ext import extract, compile_function
from rllab.algo.batch_polopt import BatchPolopt
from rllab.algo.first_order_method import FirstOrderMethod


class VPG(BatchPolopt, FirstOrderMethod):
    """
    Vanilla Policy Gradient.
    """

    @autoargs.inherit(BatchPolopt.__init__)
    @autoargs.inherit(FirstOrderMethod.__init__)
    def __init__(
            self,
            **kwargs):
        super(VPG, self).__init__(**kwargs)
        FirstOrderMethod.__init__(self, **kwargs)

    @overrides
    def init_opt(self, mdp, policy, vf):
        input_var = policy.input_var
        advantage_var = TT.vector('advantage')
        action_var = policy.new_action_var('action')
        log_prob = policy.get_log_prob_sym(action_var)
        # formulate as a minimization problem
        # The gradient of the surrogate objective is the policy gradient
        surr_obj = - TT.mean(log_prob * advantage_var)
        updates = self.update_method(surr_obj, policy.params)
        input_list = [input_var, advantage_var, action_var]
        f_update = compile_function(
            inputs=input_list,
            outputs=None,
            updates=updates,
        )
        f_loss = compile_function(
            inputs=input_list,
            outputs=surr_obj,
        )
        return dict(
            f_update=f_update,
            f_loss=f_loss,
        )

    @overrides
    def optimize_policy(self, itr, policy, samples_data, opt_info):
        logger.log("optimizing policy")
        f_update = opt_info["f_update"]
        f_loss = opt_info["f_loss"]
        inputs = extract(
            samples_data,
            "observations", "advantages", "actions"
        )
        loss_before = f_loss(*inputs)
        loss_after = f_loss(*inputs)
        f_update(*inputs)
        logger.record_tabular("LossBefore", loss_before)
        logger.record_tabular("LossAfter", loss_after)
        return opt_info

    @overrides
    def get_itr_snapshot(self, itr, mdp, policy, vf, samples_data, opt_info):
        return dict(
            itr=itr,
            policy=policy,
            vf=vf,
            mdp=mdp,
            observations=samples_data["observations"],
            advantages=samples_data["advantages"],
            actions=samples_data["actions"],
        )