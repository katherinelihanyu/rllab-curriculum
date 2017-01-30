import copy
from logging import getLogger
import os, sys
import time
import numpy as np
import chainer
from chainer import serializers
from chainer import functions as F
from chainer import links as L

from ..agents.base import Agent
from ..agents.base import Agent
from ..utils import chainer_utils
from ..utils.nonbias_weight_decay import NonbiasWeightDecay
from ..networks import dqn_head, v_function
from ..policies import policy
from ..utils.init_like_torch import init_like_torch
from ..utils.rmsprop_async import RMSpropAsync
from ..shareable.base import Shareable
from ..utils.picklable import Picklable

logger = getLogger(__name__)
import rllab.misc.logger as mylogger


class A3CModel(chainer.Link):
    def pi_and_v(self, state, keep_same_state=False):
        """
        keep_same_state: maintain the hidden states of RNN, useful for just evaluating but not moving forward in time
        """
        raise NotImplementedError()

    def reset_state(self):
        pass

    def unchain_backward(self):
        pass


class A3CLSTM(chainer.ChainList, A3CModel):
    def __init__(self, n_actions):
        self.head = dqn_head.NIPSDQNHead()
        self.pi = policy.FCSoftmaxPolicy(
            self.head.n_output_channels, n_actions)
        self.v = v_function.FCVFunction(self.head.n_output_channels)
        self.lstm = L.LSTM(self.head.n_output_channels,
                           self.head.n_output_channels)
        super().__init__(self.head, self.lstm, self.pi, self.v)
        init_like_torch(self)

    def pi_and_v(self, state, keep_same_state=False):
        out = self.head(state)
        if keep_same_state:
            prev_h, prev_c = self.lstm.h, self.lstm.c
            out = self.lstm(out)
            self.lstm.h, self.lstm.c = prev_h, prev_c
        else:
            out = self.lstm(out)
        return self.pi(out), self.v(out)

    def reset_state(self):
        self.lstm.reset_state()

    def unchain_backward(self):
        self.lstm.h.unchain_backward()
        self.lstm.c.unchain_backward()


class MultiConvHead(chainer.Chain):

    def __init__(self, n_input_channels=3, n_output_channels=128,
                 activation=F.relu, bias=0.1):
        self.n_input_channels = n_input_channels
        self.activation = activation
        self.n_output_channels = n_output_channels

        img_layers = [
            L.Convolution2D(in_channels=n_input_channels, out_channels=16, ksize=5, stride=2, bias=bias),
            L.Convolution2D(in_channels=16, out_channels=16, ksize=5, stride=1, bias=bias),
            L.Linear(2016, n_output_channels, bias=bias),
        ]
        rest_layers = [
            L.Linear(3, n_output_channels),
            L.Linear(n_output_channels, n_output_channels),
        ]
        joint_layers = [
            L.Linear(2 * n_output_channels, n_output_channels)
        ]

        self.img_layers = img_layers
        self.rest_layers = rest_layers
        self.joint_layers = joint_layers

        links = dict()

        for idx, img_layer in enumerate(img_layers):
            links["img_%d" % idx] = img_layer
        for idx, rest_layer in enumerate(rest_layers):
            links["rest_%d" % idx] = rest_layer
        for idx, joint_layer in enumerate(joint_layers):
            links["joint_%d" % idx] = joint_layer

        super(MultiConvHead, self).__init__(**links)

    def __call__(self, state):
        img, rest = state
        img_h = img
        for layer in self.img_layers:
            img_h = self.activation(layer(img_h))
        rest_h = rest
        for layer in self.rest_layers:
            rest_h = self.activation(layer(rest_h))
        h = F.concat([img_h, rest_h])
        for layer in self.joint_layers:
            h = self.activation(layer(h))
        return h


class A3CMultiConvLSTM(chainer.ChainList, A3CModel):
    def __init__(self, n_actions):
        self.head = MultiConvHead()
        self.pi = policy.FCSoftmaxPolicy(
            self.head.n_output_channels, n_actions)
        self.v = v_function.FCVFunction(self.head.n_output_channels)
        self.lstm = L.LSTM(self.head.n_output_channels,
                           self.head.n_output_channels)
        super().__init__(self.head, self.lstm, self.pi, self.v)
        init_like_torch(self)

    def pi_and_v(self, state, keep_same_state=False):
        out = self.head(state)
        if keep_same_state:
            prev_h, prev_c = self.lstm.h, self.lstm.c
            out = self.lstm(out)
            self.lstm.h, self.lstm.c = prev_h, prev_c
        else:
            out = self.lstm(out)
        return self.pi(out), self.v(out)

    def reset_state(self):
        self.lstm.reset_state()

    def unchain_backward(self):
        self.lstm.h.unchain_backward()
        self.lstm.c.unchain_backward()

class A3CAgent(Agent, Shareable, Picklable):
    """A3C: Asynchronous Advantage Actor-Critic.

    See http://arxiv.org/abs/1602.01783
    """

    def __init__(self,
                 n_actions,
                 model_type="lstm",
                 optimizer_type="rmsprop_async",
                 optimizer_args=dict(lr=7e-4, eps=1e-1, alpha=0.99),
                 optimizer_hook_args=dict(
                     gradient_clipping=40,
                 ),
                 t_max=5, gamma=0.99, beta=1e-2,
                 process_id=0, clip_reward=True,
                 keep_loss_scale_same=False,
                 phase="Train",
                 sync_t_gap_limit=np.inf,
                 ):
        self.init_params = locals()
        self.init_params.pop('self')

        if model_type == "lstm":
            self.shared_model = A3CLSTM(n_actions)
        elif model_type == "multi_conv_lstm":
            self.shared_model = A3CMultiConvLSTM(n_actions)
        else:
            raise NotImplementedError


        # Optimizer
        if optimizer_type == "rmsprop_async":
            self.optimizer = RMSpropAsync(**optimizer_args)
        else:
            raise NotImplementedError
        self.optimizer.setup(self.shared_model)
        if "gradient_clipping" in optimizer_hook_args:
            self.optimizer.add_hook(chainer.optimizer.GradientClipping(
                optimizer_hook_args["gradient_clipping"]
            ))
        if "weight_decay" in optimizer_hook_args:
            self.optimizer.add_hook(NonbiasWeightDecay(
                optimizer_hook_args["weight_decay"]
            ))
        self.init_lr = self.optimizer.lr

        # Thread specific model
        self.model = copy.deepcopy(self.shared_model)

        self.t_max = t_max  # maximum time steps before sending gradient update
        self.gamma = gamma  # discount
        self.beta = beta  # coeff for entropy bonus
        self.process_id = process_id
        self.clip_reward = clip_reward
        self.keep_loss_scale_same = keep_loss_scale_same

        self.phase = phase
        self.sync_t_gap_limit = sync_t_gap_limit

        self.t = 0
        self.t_start = 0
        self.last_sync_t = 0
        # they are dicts because the time index does not reset after finishing a traj
        self.past_action_log_prob = {}
        self.past_action_entropy = {}
        # self.past_states = {}
        self.past_actions = {}
        self.past_rewards = {}
        self.past_values = {}
        self.past_extra_infos = {}
        self.epoch_entropy_list = []
        self.epoch_path_len_list = [0]
        self.epoch_effective_return_list = [0]  # the return the agent truly sees
        self.epoch_adv_loss_list = []
        self.epoch_entropy_loss_list = []
        self.epoch_v_loss_list = []
        self.epoch_sync_t_gap_list = []
        self.cur_path_len = 0
        self.cur_path_effective_return = 0
        self.unpicklable_list = ["shared_params", "shared_model"]

    def prepare_sharing(self):
        self.shared_params = dict(
            model_params=chainer_utils.extract_link_params(self.shared_model),
        )

    def process_copy(self):
        new_agent = A3CAgent(**self.init_params)
        chainer_utils.set_link_params(
            new_agent.shared_model,
            self.shared_params["model_params"],
        )
        new_agent.sync_parameters()
        new_agent.shared_params = self.shared_params

        return new_agent

    def sync_parameters(self):
        chainer_utils.copy_link_param(
            target_link=self.model,
            source_link=self.shared_model,
        )

    def preprocess(self, state):
        if isinstance(state, np.ndarray) and len(state.shape) == 3:
            # image
            state = np.transpose(state, (2, 0, 1))
            return chainer.Variable(np.expand_dims(state, 0))
        elif isinstance(state, tuple) and isinstance(state[0], np.ndarray) and len(state[0].shape) == 3:
            img = np.transpose(state[0], (2, 0, 1))
            rest = np.asarray(state[1:], dtype=np.float32)
            return chainer.Variable(np.expand_dims(img, 0)), chainer.Variable(np.expand_dims(rest, 0))
        else:
            raise NotImplementedError
        # import ipdb; ipdb.set_trace()
        # assert state[0].dtype == np.uint8
        # processed_state = np.asarray(state, dtype=np.float32) / 255.0
        # return processed_state

    def act(self, state, reward, is_state_terminal, extra_infos=dict(), global_vars=dict(), training_args=dict()):
        # reward shaping
        if self.clip_reward:
            reward = np.clip(reward, -1, 1)
        self.past_rewards[self.t - 1] = reward

        if not is_state_terminal:
            statevar = self.preprocess(state)

        # record the time elapsed since last model synchroization
        # if the time is too long, we may discard the current update and synchronize instead
        if self.phase == "Train":
            sync_t_gap = global_vars["global_t"].value - self.last_sync_t
            not_delayed = sync_t_gap < self.sync_t_gap_limit

        ready_to_commit = self.phase == "Train" and (
            (is_state_terminal and self.t_start < self.t) \
            or self.t - self.t_start == self.t_max)
        # start computing gradient and synchronize model params
        # avoid updating model params during testing
        if ready_to_commit:
            assert self.t_start < self.t

            # assign bonus rewards

            self.cur_path_effective_return += np.sum([
                                                         self.past_rewards[i] for i in range(self.t_start, self.t)
                                                         ])

            # bootstrap total rewards for a final non-terminal state
            if is_state_terminal:
                R = 0
            else:
                _, vout = self.model.pi_and_v(statevar, keep_same_state=True)
                R = float(vout.data)

            adv_loss = 0
            entropy_loss = 0
            v_loss = 0
            # WARNING: the losses are accumulated instead of averaged over time steps
            for i in reversed(range(self.t_start, self.t)):
                R *= self.gamma
                R += self.past_rewards[i]
                v = self.past_values[i]
                # if self.process_id == 0:
                #     logger.debug('s:%s v:%s R:%s',
                #                  self.past_states[i].data.sum(), v.data, R)
                advantage = R - v
                # Accumulate gradients of policy
                log_prob = self.past_action_log_prob[i]
                entropy = self.past_action_entropy[i]

                # Log probability is increased proportionally to advantage
                adv_loss -= log_prob * float(advantage.data)
                # Entropy is maximized
                entropy_loss -= self.beta * entropy
                # Accumulate gradients of value function
                v_loss += (v - R) ** 2 / 2

            # Normalize the loss of sequences truncated by terminal states
            if self.keep_loss_scale_same and \
                                    self.t - self.t_start < self.t_max:
                factor = self.t_max / (self.t - self.t_start)
                adv_loss *= factor
                entropy_loss *= factor
                v_loss *= factor
            pi_loss = adv_loss + entropy_loss

            # if self.process_id == 0:
            #     logger.debug('adv_loss:%s, entropy_loss:%s, pi_loss:%s, v_loss:%s', adv_loss.data, entropy_loss.data,
            #                  pi_loss.data, v_loss.data)

            # note that policy and value share the same lower layers
            total_loss = pi_loss + F.reshape(v_loss, pi_loss.data.shape)

            # Update the globally shared model
            if not_delayed:
                # Compute gradients using thread-specific model
                self.model.zerograds()
                total_loss.backward()
                # Copy the gradients to the globally shared model
                self.shared_model.zerograds()
                chainer_utils.copy_link_grad(
                    target_link=self.shared_model,
                    source_link=self.model
                )
                self.optimizer.update()
            else:
                mylogger.log("Process %d banned from commiting gradient update from %d time steps ago." % (
                self.process_id, sync_t_gap))

            # log the losses
            self.epoch_adv_loss_list.append(adv_loss.data)
            self.epoch_entropy_loss_list.append(entropy_loss.data)
            self.epoch_v_loss_list.append(v_loss.data)

            self.sync_parameters()
            self.epoch_sync_t_gap_list.append(sync_t_gap)
            self.last_sync_t = global_vars["global_t"].value
            self.model.unchain_backward()

            # initialize stats for a new traj
            self.past_action_log_prob = {}
            self.past_action_entropy = {}
            # self.past_states = {}
            self.past_actions = {}
            self.past_rewards = {}
            self.past_values = {}
            self.past_extra_infos = {}

            self.t_start = self.t

        # store traj info and return action
        if not is_state_terminal:
            pout, vout = self.model.pi_and_v(statevar)
            action = pout.action_indices[0]
            if self.phase == "Train":
                # self.past_states[self.t] = statevar
                self.past_actions[self.t] = action
                self.past_action_log_prob[self.t] = pout.sampled_actions_log_probs
                self.past_action_entropy[self.t] = pout.entropy
                self.past_values[self.t] = vout
                self.past_extra_infos[self.t] = extra_infos
                self.t += 1
                # if self.process_id == 0:
                #     logger.debug('t:%s entropy:%s, probs:%s',
                #                  self.t, pout.entropy.data, pout.probs.data)
                self.epoch_entropy_list.append(pout.entropy.data)
                self.cur_path_len += 1
            else:
                self.model.unchain_backward()
            prob = pout.probs.data[0]
            return action, dict(prob=prob)
        else:
            self.epoch_path_len_list.append(self.cur_path_len)
            self.cur_path_len = 0
            self.epoch_effective_return_list.append(self.cur_path_effective_return)
            self.cur_path_effective_return = 0
            self.model.reset_state()
            return None

    def finish_epoch(self, epoch, log):
        if log:
            mylogger.record_tabular("ProcessID", self.process_id)
            mylogger.record_tabular("LearningRate", self.optimizer.lr)
            entropy = np.average(self.epoch_entropy_list)
            mylogger.record_tabular("Entropy", entropy)
            mylogger.record_tabular("Perplexity", np.exp(entropy))
            mylogger.record_tabular_misc_stat("PathLen", self.epoch_path_len_list, placement="front")
            mylogger.record_tabular_misc_stat("EffectiveReturn", self.epoch_effective_return_list, placement="front")
            mylogger.record_tabular_misc_stat(
                "AdvLoss",
                self.epoch_adv_loss_list,
                placement="front"
            )
            mylogger.record_tabular_misc_stat(
                "EntropyLoss",
                self.epoch_entropy_loss_list,
                placement="front"
            )
            mylogger.record_tabular_misc_stat(
                "ValueLoss",
                self.epoch_v_loss_list,
                placement="front"
            )
            mylogger.record_tabular_misc_stat(
                "SyncTimeGap",
                self.epoch_sync_t_gap_list,
                placement="front"
            )
        self.epoch_entropy_list = []
        self.epoch_effective_return_list = [0]
        self.epoch_path_len_list = [0]
        self.epoch_adv_loss_list = []
        self.epoch_entropy_loss_list = []
        self.epoch_v_loss_list = []
        self.epoch_sync_t_gap_list = []

        if log:
            mylogger.log(
                "Process %d finishes epoch %d with logging." % (self.process_id, epoch),
                color="green"
            )
        else:
            mylogger.log(
                "Process %d finishes epoch %d without logging." % (self.process_id, epoch),
                color="green"
            )

    def update_params(self, global_vars, training_args):
        if self.phase == "Train":
            global_t = global_vars["global_t"].value
            total_steps = training_args["total_steps"]
            self.optimizer.lr = self.init_lr * (total_steps - global_t) / total_steps
