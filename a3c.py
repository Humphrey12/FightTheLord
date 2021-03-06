import game
import os
import tensorflow as tf
import numpy as np
import tensorflow.contrib.slim as slim


def update_params(scope_from, scope_to):
    vars_from = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope_from)
    vars_to = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope_to)

    ops = []
    for from_var, to_var in zip(vars_from, vars_to):
        ops.append(to_var.assign(from_var))
    return ops


def discounted_return(r, gamma):
    r = r.astype(float)
    r_out = np.zeros_like(r)
    val = 0
    for i in reversed(range(r.shape[0])):
        r_out[i] = r[i] + gamma * val
        val = r_out[i]
    return r_out


class CardNetwork:
    def __init__(self, s_dim, trainer, scope, a_dim):
        with tf.variable_scope(scope):
            self.input = tf.placeholder(tf.float32, [None, s_dim], name="input")
            self.fc1 = slim.fully_connected(inputs=self.input, num_outputs=128, activation_fn=None)
            self.fc2 = slim.fully_connected(inputs=self.fc1, num_outputs=64, activation_fn=None)

            self.policy_pred = slim.fully_connected(inputs=self.fc2, num_outputs=a_dim, activation_fn=tf.nn.softmax)
            self.val_output = slim.fully_connected(inputs=self.fc2, num_outputs=1, activation_fn=None)
            self.val_pred = tf.reshape(self.val_output, [-1])

            self.action = tf.placeholder(tf.int32, [None], "action_input")
            self.action_one_hot = tf.one_hot(self.action, a_dim, dtype=tf.float32)

            self.val_truth = tf.placeholder(tf.float32, [None], "val_input")
            self.advantages = tf.placeholder(tf.float32, [None], "advantage_input")

            self.pi_sample = tf.reduce_sum(self.action_one_hot * self.policy_pred, [1])
            self.policy_loss = -tf.reduce_sum(tf.log(tf.clip_by_value(self.pi_sample, 1e-10, 1.)) * self.advantages)

            self.val_loss = tf.reduce_sum(tf.square(self.val_pred-self.val_truth))

            self.loss = 0.2 * self.val_loss + self.policy_loss

            local_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=scope)
            self.gradients = tf.gradients(self.loss, local_vars)

            # global_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='global')
            self.apply_grads = trainer.apply_gradients(zip(self.gradients, local_vars))


class CardAgent:
    def __init__(self, name, trainer, a_dim):
        self.name = name
        self.network = CardNetwork(54 * 3, trainer, self.name, a_dim)

    def train_batch(self, buffer, sess, gamma, val_last):
        states = buffer[:, 0]
        actions = buffer[:, 1]
        rewards = buffer[:, 2]
        values = buffer[:, 3]

        rewards_plus = np.append(rewards, val_last)
        val_truth = discounted_return(rewards_plus, gamma)[:-1]

        val_pred_plus = np.append(values, val_last)
        td0 = rewards + gamma * val_pred_plus[1:] - val_pred_plus[:-1]
        advantages = discounted_return(td0, gamma)

        sess.run(self.network.apply_grads, feed_dict={self.network.val_truth: val_truth,
                                                      self.network.advantages: advantages,
                                                      self.network.input: np.vstack(states),
                                                      self.network.action: actions})


class CardMaster:
    def __init__(self, env):
        self.name = 'global'
        self.env = env
        self.a_dim = len(self.env.action_space)
        self.gamma = 0.99
        self.train_intervals = 1
        self.trainer = tf.train.AdamOptimizer()
        self.episodes = 0
        self.episode_rewards = [[] for _ in range(3)]
        self.episode_length = [[] for _ in range(3)]
        self.episode_mean_values = [[] for _ in range(3)]
        self.summary_writer = tf.summary.FileWriter("train_" + self.name)

        self.agents = [CardAgent('agent_%d' % i, self.trainer, self.a_dim) for i in range(3)]

    def train_batch(self, buffer, sess, gamma, val_last, i):
        buffer = np.array(buffer)
        self.agents[i].train_batch(buffer, sess, gamma, val_last)

    def run(self, sess, saver, max_episode_length):
        with sess.as_default():
            for i in range(1001):
                print("episode %d" % i)
                episode_buffer = [[] for _ in range(3)]
                episode_values = [[] for _ in range(3)]
                episode_reward = [0, 0, 0]
                episode_steps = [0, 0, 0]

                self.env.reset()
                self.env.players[0].trainable = True
                self.env.players[1].trainable = True
                self.env.players[2].trainable = True
                self.env.prepare(0)

                s = self.env.get_state(0)
                s = np.reshape(s, [1, -1])

                for l in range(max_episode_length):
                    curr_id = self.env.next_turn
                    print("turn %d, player: %d" % (l, curr_id))
                    policy, val = sess.run([self.agents[curr_id].network.policy_pred, self.agents[curr_id].network.val_pred],
                                            feed_dict={self.agents[curr_id].network.input: s})
                    mask = self.env.get_mask(curr_id)
                    valid_actions = np.take(np.arange(self.a_dim), mask.nonzero())
                    valid_actions = valid_actions.reshape(-1)
                    valid_p = np.take(policy[0], mask.nonzero())
                    valid_p = valid_p / np.sum(valid_p)
                    valid_p = valid_p.reshape(-1)
                    a = np.random.choice(valid_actions, p=valid_p)

                    _, done = self.env.step(curr_id, a)
                    s_prime = self.env.get_state(curr_id)
                    s_prime = np.reshape(s_prime, [1, -1])

                    episode_buffer[curr_id].append([s, a, 0, val[0]])
                    episode_values[curr_id].append(val)
                    episode_reward[curr_id] += 0
                    episode_steps[curr_id] += 1

                    if done:
                        for j in range(3):
                            if j == curr_id:
                                r = 1
                            elif curr_id == self.env.lord_idx:
                                r = -1
                            elif j == self.env.lord_idx:
                                r = -1
                            else:
                                r = 1
                            # replace the reward
                            episode_buffer[j][-1][2] = r
                            episode_reward[j] += r
                            self.train_batch(episode_buffer[j], sess, self.gamma, 0, j)
                            self.episode_mean_values[j].append(np.mean(episode_values[j]))
                            self.episode_length[j].append(episode_steps[j])
                            self.episode_rewards[j].append(episode_reward[j])
                        break
                    s = s_prime

                    # if len(episode_buffer) == self.train_intervals:
                    #     val_last = sess.run(self.agent.network.val_pred,
                    #                         feed_dict={self.agent.network.input: s})
                    #     self.train_batch(episode_buffer, sess, self.gamma, val_last[0])
                    #     episode_buffer = []

                if i % 5 == 0 and i > 0:
                    if i % 250 == 0:
                        saver.save(sess, './model' + '/model-' + str(i) + '.cptk')
                        print ("Saved Model")
                    for j in range(3):
                        mean_reward = np.mean(self.episode_rewards[j][-5:])
                        mean_length = np.mean(self.episode_length[j][-5:])
                        mean_value = np.mean(self.episode_mean_values[j][-5:])
                        summary = tf.Summary()
                        summary.value.add(tag='rewards %d' % j, simple_value=float(mean_reward))
                        summary.value.add(tag='length %d' % j, simple_value=float(mean_length))
                        summary.value.add(tag='values %d' % j, simple_value=float(mean_value))
                        self.summary_writer.add_summary(summary, i)
                        self.summary_writer.flush()


def run_game(sess, network):
    max_episode_length = 100
    lord_win_rate = 0
    for i in range(100):
        network.env.reset()
        network.env.players[0].trainable = True
        lord_idx = 2
        network.env.players[2].is_human = True
        network.env.prepare(lord_idx)

        s = network.env.get_state(0)
        s = np.reshape(s, [1, -1])

        while True:
            policy, val = sess.run([network.agent.network.policy_pred, network.agent.network.val_pred],
                                   feed_dict={network.agent.network.input: s})
            mask = network.env.get_mask(0)
            valid_actions = np.take(np.arange(network.a_dim), mask.nonzero())
            valid_actions = valid_actions.reshape(-1)
            valid_p = np.take(policy[0], mask.nonzero())
            if np.count_nonzero(valid_p) == 0:
                valid_p = np.ones([valid_p.size]) / float(valid_p.size)
            else:
                valid_p = valid_p / np.sum(valid_p)
            valid_p = valid_p.reshape(-1)
            a = np.random.choice(valid_actions, p=valid_p)

            r, done = network.env.step(0, a)
            s_prime = network.env.get_state(0)
            s_prime = np.reshape(s_prime, [1, -1])

            if done:
                idx = network.env.check_winner()
                if idx == lord_idx:
                    lord_win_rate += 1
                print("winner is player %d" % idx)
                print("..............................")
                break
            s = s_prime
    print("lord winning rate: %f" % (lord_win_rate / 100.0))


if __name__ == '__main__':
    os.system("rm -r ./train_global/")
    load_model = False
    model_path = './model'
    cardgame = game.Game()
    with tf.device("/gpu:0"):
        master = CardMaster(cardgame)
    saver = tf.train.Saver(max_to_keep=5)
    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        if load_model:
            print ('Loading Model...')
            ckpt = tf.train.get_checkpoint_state(model_path)
            saver.restore(sess, ckpt.model_checkpoint_path)
            run_game(sess, master)
        else:
            sess.run(tf.global_variables_initializer())
            master.run(sess, saver, 2000)
        sess.close()
