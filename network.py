import os, h5py

import numpy as np
import tensorflow as tf
from tqdm import trange

from config import get_config, print_usage
from util.preprocessing import package_data


class Network:
    def __init__(self, x_shp, config):

        self.config = config

        # Get shape
        self.x_shp = x_shp

        # Build the network
        self._build_placeholder()
        self._build_preprocessing()
        self._build_model()
        self._build_loss()
        self._build_optim()
        self._build_eval()
#        self._build_summary()
#        self._build_writer()

    def _build_placeholder(self):
        """Build placeholders."""

        # Get shape for placeholder
        x_in_shp = (None, *self.x_shp[1:])
        
        # Create Placeholders for inputs
        self.x_in = tf.placeholder(tf.float32, shape=x_in_shp)
        self.y_in = tf.placeholder(tf.int64, shape=(None, ))
        
    def _build_preprocessing(self):
        """Build preprocessing related graph."""

        with tf.variable_scope("Normalization", reuse=tf.AUTO_REUSE):
            # we will make `n_mean`, `n_range`, `n_mean_in` and
            # `n_range_in` as scalar this time! This is how we often use in
            # CNNs, as we KNOW that these are image pixels, and all pixels
            # should be treated equally!

            # Create placeholders for saving mean, range to a TF variable for
            # easy save/load. Create these variables as well.
            self.n_mean_in = tf.placeholder(tf.float32, shape=())
            self.n_range_in = tf.placeholder(tf.float32, shape=())
            # Make the normalization as a TensorFlow variable. This is to make
            # sure we save it in the graph
            self.n_mean = tf.get_variable(
                "n_mean", shape=(), trainable=False)
            self.n_range = tf.get_variable(
                "n_range", shape=(), trainable=False)
            # Assign op to store this value to TF variable
            self.n_assign_op = tf.group(
                tf.assign(self.n_mean, self.n_mean_in),
                tf.assign(self.n_range, self.n_range_in),
            )

    def _build_optim(self):
        """Build optimizer related ops and vars."""

        with tf.variable_scope("Optim", reuse=tf.AUTO_REUSE):
            self.global_step = tf.get_variable(
                "global_step", shape=(),
                initializer=tf.zeros_initializer(),
                dtype=tf.int64,
                trainable=False)
            optimizer = tf.train.AdamOptimizer(
                learning_rate=self.config.learning_rate)
            self.optim = optimizer.minimize(
                self.loss, global_step=self.global_step)
            
    def _build_eval(self):
        """Build the evaluation related ops"""

        with tf.variable_scope("Eval", tf.AUTO_REUSE):

            # Compute the accuracy of the model. When comparing labels
            # elemwise, use tf.equal instead of `==`. `==` will evaluate if
            # your Ops are identical Ops.
            self.pred = tf.argmax(self.logits, axis=1)
            self.acc = tf.reduce_mean(
                tf.to_float(tf.equal(self.pred, self.y_in))
            )

            # Record summary for accuracy
            tf.summary.scalar("accuracy", self.acc)

            # We also want to save best validation accuracy. So we do
            # something similar to what we did before with n_mean. Note that
            # these will also be a scalar variable
            self.best_va_acc_in = tf.placeholder(tf.float32, shape=())
            self.best_va_acc = tf.get_variable(
                "best_va_acc", shape=(), trainable=False)
            # TODO: Assign op to store this value to TF variable
            self.acc_assign_op = tf.assign(self.best_va_acc, self.best_va_acc_in)     
    def _build_model(self):
        """Build our MLP network."""

        # Initializer and activations
        if self.config.activ_type == "relu":
            activ = tf.nn.relu
            kernel_initializer = tf.keras.initializers.he_normal()
        elif self.config.activ_type == "tanh":
            activ = tf.nn.tanh
            kernel_initializer = tf.glorot_normal_initializer()

        # Build the network (use tf.layers)
        with tf.variable_scope("Network", reuse=tf.AUTO_REUSE):
            # Normalize using the above training-time statistics
            cur_in = (self.x_in - self.n_mean) / self.n_range
            # Convolutional layer 0. Make output shape become 32 > 28 >
            # 14 as we do convolution and pooling. We will also use the
            # argument from the configuration to determine the number of
            # filters for the inital conv layer. Have `num_unit` of filters,
            # use the kernel_initializer above.
            num_unit = self.config.num_unit

            cur_in = tf.layers.conv2d(inputs=cur_in,
                                      filters=self.config.num_conv_base,
                                      kernel_size=5,
                                      kernel_initializer=kernel_initializer,
                                      padding='valid',
                                      activation=activ)
            # use `tf.layers.max_pooling2d` to see how it should run. If
            # you want to try different pooling strategies, add it as another
            # config option. Be sure to have the max_pooling implemented.
            cur_in = tf.layers.max_pooling2d(inputs=cur_in,
                                             pool_size=[2, 2],
                                             strides=2)

            # double the number of filters we will use after pooling
            conv_filters = 2 * self.config.num_conv_base
            # TODO: Convolutional layer 1. Make output shape become 14 > 12 > 6
            # as we do convolution and pooling. Have `num_unit` of filters,
            # use the kernel_initializer above.
            cur_in = tf.layers.conv2d(inputs=cur_in,
                          filters=conv_filters,
                          kernel_size=3,
                          kernel_initializer=kernel_initializer,
                          activation=activ)


            # max pooling
            cur_in = tf.layers.max_pooling2d(inputs=cur_in,
                                             pool_size=[2, 2],
                                             strides=2)

            # double the number of filters we will use after pooling
            conv_filters = 2 * conv_filters
            # Convolutional layer 2. Make output shape become 6 > 4 > 2
            # as we do convolution and pooling. Have `num_unit` of filters,
            # use the kernel_initializer above.
            cur_in = tf.layers.conv2d(inputs=cur_in,
                          filters=conv_filters,
                          kernel_size=3,
                          kernel_initializer=kernel_initializer,
                          activation=activ)

            # max pooling
            cur_in = tf.layers.max_pooling2d(inputs=cur_in,
                                             pool_size=[2, 2],
                                             strides=2)
            
            # Flatten to put into FC layer with `tf.layers.flatten`
            cur_in = tf.layers.flatten(cur_in)
            # Hidden layers
            num_unit = self.config.num_unit
            for _i in range(self.config.num_hidden):
                cur_in = tf.layers.dense(
                    cur_in, num_unit, kernel_initializer=kernel_initializer)
                if self.config.activ_type == "relu":
                    cur_in = tf.nn.relu(cur_in)
                elif self.config.activ_type == "tanh":
                    cur_in = tf.nn.tanh(cur_in)
            # Output layer
            self.logits = tf.layers.dense(
                cur_in, self.config.num_class,
                kernel_initializer=kernel_initializer)

            # Get list of all weights in this scope. They are called "kernel"
            # in tf.layers.dense.
            self.kernels_list = [
                _v for _v in tf.trainable_variables() if "kernel" in _v.name]    

    def train(self, x_tr, y_tr, x_va, y_va):
        """Training function.

        Parameters
        ----------
        x_tr : ndarray
            Training data.

        y_tr : ndarray
            Training labels.

        x_va : ndarray
            Validation data.

        y_va : ndarray
            Validation labels.

        """

        # ----------------------------------------
        # Preprocess data

        # We will simply use the data_mean for x_tr_mean, and 128 for the range
        # as we are dealing with image and CNNs now
        x_tr_mean = x_tr.mean()
        x_tr_range = 128.0

        # Report data statistic
        print("Training data before: mean {}, std {}, min {}, max {}".format(
            x_tr_mean, x_tr.std(), x_tr.min(), x_tr.max()
        ))

        # ----------------------------------------
        # Run TensorFlow Session
        with tf.Session() as sess:
            # Init
            print("Initializing...")
            sess.run(tf.global_variables_initializer())

            # Assign normalization variables from statistics of the train data
            sess.run(self.n_assign_op, feed_dict={
                self.n_mean_in: x_tr_mean,
                self.n_range_in: x_tr_range,
            })

     
            step = 0
            best_acc = 0

            print("Training...")
            batch_size = config.batch_size
            max_iter = config.max_iter
            # For each epoch
            for step in trange(step, max_iter):

                # Get a random training batch. Notice that we are now going to
                # forget about the `epoch` thing. Theoretically, they should do
                # almost the same.
                ind_cur = np.random.choice(
                    len(x_tr), batch_size, replace=False)
                x_b = np.array([x_tr[_i] for _i in ind_cur])
                y_b = np.array([y_tr[_i] for _i in ind_cur])

                # TODO: Write summary every N iterations as well as the first
                # iteration. Use `self.config.report_freq`. Make sure that we
                # write at the first iteration, and every kN iterations where k
                # is an interger. HINT: we write the summary after we do the
                # optimization.
#                b_write_summary = (step % self.config.report_freq) == 0
#                if b_write_summary:
#                    fetches = {
#                        "optim": self.optim,
#                        "summary": self.summary_op,
#                        "global_step": self.global_step,
#                    }
#                else:
                fetches = {
                    "optim": self.optim,
                }

                # Run the operations necessary for training
                res = sess.run(
                    fetches=fetches,
                    feed_dict={
                        self.x_in: x_b,
                        self.y_in: y_b,
                    },
                )

                # Write Training Summary if we fetched it (don't write
                # meta graph). See that we actually don't need the above
                # `b_write_summary` actually :-). I know that we can check this
                # with b_write_summary, but let's check `res` to do this as an
                # exercise.
#                if "summary" in res:
#                    self.summary_tr.add_summary(
#                        res["summary"], global_step=res["global_step"],
#                    )
#                    self.summary_tr.flush()
#
#                    # Also save current model to resume when we write the
#                    # summary.
#                    self.saver_cur.save(
#                        sess, self.save_file_cur,
#                        global_step=self.global_step,
#                        write_meta_graph=False,
#                    )

                # Validate every N iterations and at the first
                # iteration. Use `self.config.val_freq`. Make sure that we
                # validate at the correct iterations. HINT: should be similar
                # to above.
                b_validate = (step % self.config.report_freq) == 0
                if b_validate:
                    res = sess.run(
                        fetches={
                            "acc": self.acc,
                            "summary": self.summary_op,
                            "global_step": self.global_step,
                        },
                        feed_dict={
                            self.x_in: x_va,
                            self.y_in: y_va
                        })
#                    # Write Validation Summary
#                    self.summary_va.add_summary(
#                        res["summary"], global_step=res["global_step"],
#                    )
                    self.summary_va.flush()

                    # If best validation accuracy, update W_best, b_best, and
                    # best accuracy. We will only return the best W and b
                    if res["acc"] > best_acc:
                        best_acc = res["acc"]
                        # TODO: Write best acc to TF variable
                        sess.run(self.acc_assign_op, feed_dict={
                            self.best_va_acc_in: best_acc
                        })

                        # Save the best model
#                        self.saver_best.save(
#                            sess, self.save_file_best,
#                            write_meta_graph=False,
#                        )
    def _build_loss(self):
        """Build our cross entropy loss."""

        with tf.variable_scope("Loss", reuse=tf.AUTO_REUSE):

            # Create cross entropy loss
            self.loss = tf.reduce_mean(
                tf.nn.sparse_softmax_cross_entropy_with_logits(
                    labels=self.y_in, logits=self.logits)
            )

            # Create l2 regularizer loss and add
            l2_loss = tf.add_n([
                tf.reduce_sum(_v**2) for _v in self.kernels_list])
            self.loss += self.config.reg_lambda * l2_loss

            # Record summary for loss
            tf.summary.scalar("loss", self.loss)            
            
def main(config):
    """The main function."""

    # Package data from directory into HD5 format
    if config.package_data:
        print("Packaging data into H5 format...")
        package_data(config.data_dir)
    else:
        print("Packaging data skipped.")
        
    # Load packaged data
    print("Loading data...")
    f = h5py.File('videoData.h5', 'r')
    data = []
    for group in f:
        """
        Keys of groups:    
        ['class_colour',
         'class_id',
         'frame-10s',
         'info',
         'instance_colour',
         'instance_id',
         'raw_images',
         'video']
        """
        data.append(f[group])
    
    d = data[0]
    net = Network(d['video'].shape, config)
    
    
    net.train()


#
#def loss(inp, out, n_c):
#    return 1


#def train(x, y, config): 
#    
#    with tf.Session() as sess:
#        print("Initializing...")
#        sess.run(tf.global_variables_initializer())
#        global_step = tf.get_variable(
#                "global_step", shape=(),
#                initializer=tf.zeros_initializer(),
#                dtype=tf.int64,
#                trainable=False)
#        
#        lr = config.learning_rate
#        opt = tf.train.AdamOptimizer()
#        num_classes = y.shape[1]
#        x_in_shp = (None, *x.shape[1:])
#        
#        # Create Placeholders for inputs
#        x_in = tf.placeholder(tf.float32, shape=x_in_shp)
#        y_in = tf.placeholder(tf.int64, shape=(None, ))
#        loss = loss(x_in, y_in, num_classes)
#        minimize = opt.minimize(
#                loss, global_step=global_step)
#        
#        ######## Done opt
#        batch_size = config.batch_size
#        max_iter = config.max_iter
#            # For each epoch
#        for step in trange(step, max_iter):
#            ind_cur = np.random.choice(
#                len(x_tr), batch_size, replace=False)
#            x_b = np.array([x_tr[_i] for _i in ind_cur])
#            y_b = np.array([y_tr[_i] for _i in ind_cur])\
#            
#            res = sess.run(
#                    fetches=[minimize],
#                    feed_dict={
#                        x_in: x_b,
#                        y_in: y_b,
#                    },
#                )
#            
    
if __name__ == "__main__":

    # Parse configuration
    config, unparsed = get_config()
    # If we have unparsed arguments, print usage and exit
    if len(unparsed) > 0:
        print_usage()
        exit(1)

    main(config)

