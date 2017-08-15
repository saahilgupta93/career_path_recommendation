import os
import numpy as np
import tensorflow as tf

from baseline_model import BaselineModel
from read_data import read_ontology_data
from split_data import create_train_test_set_stratified_nemo


# TODO: think about adding education
class NEMO(BaselineModel):
    def __init__(self, n_files,threshold=5, restore=False):
        self.threshold = threshold
        self.X_skill_train,self.X_skill_test = create_train_test_set_stratified_nemo(data_file_name='skill_store',
                                                                                     n_files=n_files,
                                                                                     threshold=self.threshold)
        self.X_job_train, self.X_job_test = create_train_test_set_stratified_nemo(data_file_name='job_store',
                                                                                      n_files=n_files,
                                                                                      threshold=self.threshold)
        self.seqlen_train, self.seqlen_test = create_train_test_set_stratified_nemo(data_file_name='seqlen_store',
                                                                                    n_files=n_files,
                                                                                    threshold=self.threshold)
        self.y_train, self.y_test = create_train_test_set_stratified_nemo(data_file_name='label_store',
                                                                                  n_files=n_files,
                                                                                  threshold=self.threshold)
        self.embedding_size = 100
        self.restore = restore
        BaselineModel.__init__(self, self.X_skill_train, self.X_skill_train)
        _,_,self.job_dict,self.reverse_job_dict = self.prepare_feature_generation()
        self.initialize_values()
        self.y_train = np.array([self.job_reduce_dict[job] for job in self.y_train])
        self.y_test = np.array([self.job_reduce_dict[job] for job in self.y_test])
        self.compute_graph()

    def initialize_values(self):
        self.class_labels = np.unique(np.concatenate((self.y_train, self.y_test)))
        self.n_unique_jobs = len(list(self.class_labels))
        print('Number of unique job titles: ',self.n_unique_jobs)

        # skill reduce dict
        self.job_reduce_dict = {}
        self.reverse_job_reduce_dict = {}
        for i, job in enumerate(self.class_labels):
            self.job_reduce_dict[job] = i
            self.reverse_job_reduce_dict[i] = job

        self.reduced_class_labels = np.array(range(self.n_unique_jobs))

        return self

    def generate_random_batches(self, X_skill, X_job, X_seqlen, y, batch_size):
        idx = np.random.randint(0,len(X_job),batch_size)
        X_skill_batch = X_skill[idx,:]
        X_job_batch = X_job[idx,:,:]
        X_seqlen_batch = X_seqlen[idx,]
        y_batch = np.expand_dims(y[idx,],axis=1)
        return X_skill_batch,X_job_batch,X_seqlen_batch, y_batch

    def compute_graph(self):
        # define the compute graph with everything as 'self'
        # need to include a definition of mpr here

        # general definitions
        self.sess = tf.Session()

        self.batch_size = 1000
        self.max_roles = 10
        self.embedding_size = 100
        self.n_linear_hidden = self.embedding_size
        self.n_lstm_hidden = 100
        self.number_of_layers = 3

        ###########
        # encoder
        ###########

        self.max_pool_skills = tf.placeholder(dtype=tf.float32,shape=(None,self.embedding_size))
        # add university perhaps in the future + location

        # one layer NN
        with tf.variable_scope("encoder"):
            self.concat_rep = self.max_pool_skills
            self.W_linear = tf.Variable(tf.truncated_normal(shape=(int(self.concat_rep.get_shape()[1]),self.n_linear_hidden)))
            self.b_linear = tf.Variable(tf.constant(0.1,shape=(self.n_linear_hidden,)))
            self.encoder_output = tf.tanh(tf.matmul(self.concat_rep,self.W_linear) + self.b_linear)
            # self.encoder_output = tf.Variable(tf.truncated_normal(shape=(None,
            #                                                              int(self.max_pool_skills.get_shape()[1]))))

        ###########
        # decoder
        ###########

        self.job_inputs = tf.placeholder(tf.float32, shape=(None, self.max_roles - 1, self.embedding_size))
        self.seqlen = tf.placeholder(tf.int32, shape=(None,))
        self.job_true = tf.placeholder(tf.int32,shape=(None,1))

        self.encoder_output = tf.expand_dims(self.encoder_output,axis=1)
        self.encoded_job_inputs = tf.concat([self.encoder_output,self.job_inputs],axis=1)
        self.lstm = tf.contrib.rnn.BasicLSTMCell(self.n_lstm_hidden, state_is_tuple=True)
        # self.lstm = tf.nn.rnn_cell.GRUCell(self.n_lstm_hidden)
        # self.stacked_lstm = tf.contrib.rnn.MultiRNNCell(cells=[self.lstm for _ in range(self.number_of_layers)],state_is_tuple=True)

        with tf.variable_scope("decoder"):
            self.job_outputs, self.last_states = tf.nn.dynamic_rnn(self.lstm, self.encoded_job_inputs,
                                                    sequence_length=self.seqlen,
                                                    initial_state=self.lstm.zero_state(tf.shape(self.job_inputs)[0], tf.float32))

        # output
        # self.final_job_output = tf.gather_nd(self.job_outputs,self.seqlen)
        self.actual_batch_size = tf.shape(self.job_inputs)[0]
        self.final_job_output = tf.gather_nd(self.job_outputs, tf.stack([tf.range(self.actual_batch_size), self.seqlen - 1], axis=1))

        self.W_output = tf.Variable(tf.truncated_normal(shape=(self.n_lstm_hidden, self.n_unique_jobs)))
        self.b_output = tf.Variable(tf.constant(0.1, shape=(self.n_unique_jobs,)))
        self.logits = tf.matmul(self.final_job_output,self.W_output) + self.b_output

        # calculate loss
        # training
        # self.softmax_size = 50
        # self.W_softmax = tf.get_variable("proj_w", [self.n_unique_jobs, self.n_unique_jobs], dtype=tf.float32)
        # self.b_softmax = tf.get_variable("proj_b", [self.n_unique_jobs], dtype=tf.float32)
        # self.train_loss = tf.nn.sampled_softmax_loss(weights=self.W_softmax,
        #                                     biases=self.b_softmax,
        #                                     labels=self.job_true,
        #                                     inputs=self.logits,
        #                                     num_sampled=self.softmax_size,
        #                                     num_classes=self.n_unique_jobs,
        #                                     partition_strategy="div")


        self.loss = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(labels=tf.squeeze(self.job_true,axis=1),
                                                                                  logits=self.logits))
        self.train_step = tf.train.AdamOptimizer().minimize(self.loss)
        self.test_probs = tf.nn.softmax(self.logits) # shape: [batch_size x unique_jobs]

        return self

    def nemo_mpr(self,y_pred_proba,y_true):
        mpr = np.mean([np.where(self.reduced_class_labels[y_pred_proba[i].argsort()[::-1]] == y_true[i])[0][0] / len(self.reduced_class_labels)
                       for i in range(len(y_true))
                       if y_true[i] in self.reduced_class_labels])
        return mpr

    def run_nemo_model(self, n_iter, print_freq, model_name):

        saver = tf.train.Saver()
        folder_name = 'saved_models/' + model_name + '/'
        file_name = 'saved_model'

        # restore the model
        if self.restore:
            print('Restoring ', model_name, '...')
            saver = tf.train.import_meta_graph(folder_name + file_name + '.meta')
            saver.restore(self.sess, tf.train.latest_checkpoint(folder_name))

        # train the model
        else:

            self.sess.run(tf.global_variables_initializer())

            for iter in range(n_iter):
                X_skill_batch,X_job_batch,X_seqlen_batch, y_batch = self.generate_random_batches(self.X_skill_train,
                                                                                                 self.X_job_train,
                                                                                                 self.seqlen_train,
                                                                                                 self.y_train,
                                                                                                 batch_size=self.batch_size)
                train_feed_dict = {self.max_pool_skills: X_skill_batch,
                                   self.job_inputs: X_job_batch[:,:self.max_roles-1,:],
                                   self.seqlen: X_seqlen_batch,
                                   self.job_true: y_batch}
                self.sess.run([self.train_step],train_feed_dict)

                if iter % print_freq == 0:
                    test_feed_dict = {self.max_pool_skills: self.X_skill_test,
                                      self.job_inputs: self.X_job_test[:,:self.max_roles-1,:],
                                      self.seqlen: self.seqlen_test,
                                      self.job_true: np.expand_dims(self.y_test, axis=1)}

                    train_loss = self.sess.run(self.loss, train_feed_dict)
                    test_loss = self.sess.run(self.loss, test_feed_dict)

                    print('Train Loss at', iter, ": ", train_loss)
                    print('Test Loss:', test_loss)

            # saving model
            if not os.path.exists(model_name):
                os.mkdir(model_name)
            saver.save(self.sess, folder_name + file_name)

        return self


    # # TODO: test this
    # def restore_nemo_model(self, model_name):
    #     folder_name = 'saved_models/' + model_name + '/'
    #     file_name = 'saved_model.meta'
    #     with tf.Session() as sess:
    #         # restore graph
    #         new_saver = tf.train.import_meta_graph(folder_name + file_name)
    #         new_saver.restore(sess, tf.train.latest_checkpoint(folder_name))
    #         # print(sess.run('w1:0'))
    #
    #         # do something useful with graph
    #         graph = tf.get_default_graph()
    #         self.max_pool_skills = graph
    #         self.job_inputs = tf.placeholder(tf.float32, shape=(None, self.max_roles - 1, self.embedding_size))
    #         self.seqlen = tf.placeholder(tf.int32, shape=(None,))
    #         self.job_true = tf.placeholder(tf.int32, shape=(None, 1))
    #
    #     # https://stackoverflow.com/questions/42832083/tensorflow-saving-restoring-session-checkpoint-metagraph
    #
    #     return self

    def evaluate_nemo(self):
        # evaluate relevant variables from compute graph
        print('evaluating...')
        test_feed_dict = {self.max_pool_skills: self.X_skill_test,
                          self.job_inputs: self.X_job_test[:,:self.max_roles-1,:],
                          self.seqlen: self.seqlen_test,
                          self.job_true: np.expand_dims(self.y_test, axis=1)}
        test_loss, test_probs = self.sess.run([self.loss, self.test_probs], test_feed_dict)
        print('Test Loss: ', test_loss)

        # calculating MPR
        print('calculating MPR')
        mpr = self.nemo_mpr(test_probs, self.y_test)

        return mpr

    # TODO: complete this
    def test_individual_examples(self):
        # take random example from initial df

        # convert this into terms that NEMO would understand

        # run through the compute graph

        # output a prob

        # use reverse dict to convert into prediction
        pass


if __name__ == "__main__":

    model = NEMO(n_files=1,restore=True)
    # print(model.X_job_train.shape)
    # # model.restore_nemo_model(model_name='first_run')
    model.run_nemo_model(n_iter=2000,print_freq=1000,model_name='test_run')
    mpr = model.evaluate_nemo()
    print('MPR:',mpr)
    # model.restore_nemo_model('test_run')

    # # test mpr
    # test_array = np.random.rand(10,100)
    # y_true = np.random.randint(0,100,size=(10,))
    # class_labels = np.array(range(100))
    #
    # mpr = model.nemo_mpr(test_array,y_true,class_labels)
    # print('MPR is: ', mpr)

    # test gather_nd
