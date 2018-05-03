# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************

from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import

import gzip
import os

import numpy as np
from neon.data import Dataset
from neon.data.text_preprocessing import pad_sentences

from nlp_architect.utils.generic import get_paddedXY_sequence
from nlp_architect.contrib.neon.text_iterators import TaggedTextSequence, MultiSequenceDataIterator
from nlp_architect.utils.embedding import load_word_embeddings


class CONLL2000(Dataset):
    """
    CONLL 2000 chunking task data set (Neon)

    Arguments:
        sentence_length (int): number of time steps to embed the data.
        vocab_size (int): max size of vocabulary.
        path (str, optional): Path to data file.
        use_pos (boolean, optional): Yield POS tag features.
        use_chars (boolean, optional): Yield Char RNN features.
        use_w2v (boolean, optional): Use W2V as input features.
        w2v_path (str, optional): W2V model path
    """

    def __init__(self, path='.', sentence_length=50, vocab_size=20000,
                 use_pos=False,
                 use_chars=False,
                 chars_len=20,
                 use_w2v=False,
                 w2v_path=None):
        url = 'https://raw.githubusercontent.com/teropa/nlp/master/resources/corpora/conll2000/'
        self.filemap = {'train': 2842164,
                        'test': 639396}
        self.file_names = ['{}.txt'.format(phase) for phase in self.filemap]
        sizes = [self.filemap[phase] for phase in self.filemap]
        super(CONLL2000, self).__init__(self.file_names,
                                        url,
                                        sizes,
                                        path=path)
        self.sentence_length = sentence_length
        self.vocab_size = vocab_size
        self.use_pos = use_pos
        self.use_chars = use_chars
        self.chars_len = chars_len
        self.use_w2v = use_w2v
        self.w2v_path = w2v_path
        self.vocabs = {}

    def load_gzip(self, filename, size):
        """
        Helper function for downloading test files
        Will download and un-gzip the file into the directory self.path

        Arguments:
            filename (str): name of file to download from self.url
            size (str): size of the file in bytes?

        Returns:
            str: Path to the downloaded dataset.
        """
        _, filepath = self._valid_path_append(self.path, '', filename)

        if not os.path.exists(filepath):
            self.fetch_dataset(self.url, filename, filepath, size)
        if '.gz' in filepath:
            with gzip.open(filepath, 'rb') as fp:
                file_content = fp.readlines()
            filepath = filepath.split('.gz')[0]
            with open(filepath, 'wb') as fp:
                fp.writelines(file_content)
        return filepath

    def load_data(self):
        file_data = {}
        for phase in self.filemap:
            size = self.filemap[phase]
            phase_file = self.load_zip('{}.txt'.format(phase), size)
            file_data[phase] = self.parse_entries(phase_file)
        return file_data['train'], file_data['test']

    @staticmethod
    def parse_entries(filepath):
        texts = []
        block = []
        with open(filepath, 'r', encoding='utf-8') as fp:
            for line in fp:
                if len(line.strip()) == 0:
                    if len(block) > 1:
                        texts.append(list(zip(*block)))
                    block = []
                else:
                    block.append([e.strip() for e in line.strip().split()])
        return texts

    def create_char_features(self, sentences, sentence_length, word_length):
        char_dict = {}
        char_id = 3
        new_sentences = []
        for s in sentences:
            char_sents = []
            for w in s:
                char_vector = []
                for c in w:
                    char_int = char_dict.get(c, None)
                    if char_int is None:
                        char_dict[c] = char_id
                        char_int = char_id
                        char_id += 1
                    char_vector.append(char_int)
                char_vector = [1] + char_vector + [2]
                char_sents.append(char_vector)
            char_sents = pad_sentences(char_sents, sentence_length=word_length)
            if sentence_length - char_sents.shape[0] < 0:
                char_sents = char_sents[:sentence_length]
            else:
                padding = np.zeros(
                    (sentence_length - char_sents.shape[0], word_length))
                char_sents = np.vstack((padding, char_sents))
            new_sentences.append(char_sents)
        char_sentences = np.asarray(new_sentences)
        self.vocabs.update({'char_rnn': char_dict})
        return char_sentences

    def gen_iterators(self):
        train_set, test_set = self.load_data()
        num_train_samples = len(train_set)

        sents = list(zip(*train_set))[0] + list(zip(*test_set))[0]
        X, X_vocab = self._sentences_to_ints(sents, lowercase=False)
        self.vocabs.update({'token': X_vocab})

        y = list(zip(*train_set))[2] + list(zip(*test_set))[2]
        y, y_vocab = self._sentences_to_ints(y, lowercase=False)
        self.y_vocab = y_vocab
        X, y = get_paddedXY_sequence(
            X, y, sentence_length=self.sentence_length, shuffle=False)

        self._data_dict = {}
        self.y_size = len(y_vocab) + 1
        train_iters = []
        test_iters = []

        if self.use_w2v:
            w2v_dict, emb_size = load_word_embeddings(self.w2v_path)
            self.emb_size = emb_size
            x_vocab_is = {i: s for s, i in X_vocab.items()}
            X_w2v = []
            for xs in X:
                _xs = []
                for w in xs:
                    if 0 <= w <= 2:
                        _xs.append(np.zeros(emb_size))
                    else:
                        word = x_vocab_is[w - 3]
                        vec = w2v_dict.get(word.lower())
                        if vec is not None:
                            _xs.append(vec)
                        else:
                            _xs.append(np.zeros(emb_size))
                X_w2v.append(_xs)
            X_w2v = np.asarray(X_w2v)
            train_iters.append(TaggedTextSequence(self.sentence_length,
                                                  x=X_w2v[:num_train_samples],
                                                  y=y[:num_train_samples],
                                                  num_classes=self.y_size,
                                                  vec_input=True))
            test_iters.append(TaggedTextSequence(self.sentence_length,
                                                 x=X_w2v[num_train_samples:],
                                                 y=y[num_train_samples:],
                                                 num_classes=self.y_size,
                                                 vec_input=True))
        else:
            train_iters.append(TaggedTextSequence(self.sentence_length,
                                                  x=X[:num_train_samples],
                                                  y=y[:num_train_samples],
                                                  num_classes=self.y_size))
            test_iters.append(TaggedTextSequence(self.sentence_length,
                                                 x=X[num_train_samples:],
                                                 y=y[num_train_samples:],
                                                 num_classes=self.y_size))

        if self.use_pos:
            pos_sents = list(zip(*train_set))[1] + list(zip(*test_set))[1]
            X_pos, X_pos_vocab = self._sentences_to_ints(pos_sents)
            self.vocabs.update({'pos': X_pos_vocab})
            X_pos, _ = get_paddedXY_sequence(X_pos, y, sentence_length=self.sentence_length,
                                             shuffle=False)
            train_iters.append(TaggedTextSequence(steps=self.sentence_length,
                                                  x=X_pos[:num_train_samples]))
            test_iters.append(TaggedTextSequence(steps=self.sentence_length,
                                                 x=X_pos[num_train_samples:]))

        if self.use_chars:
            char_sentences = self.create_char_features(
                sents, self.sentence_length, self.chars_len)
            char_sentences = char_sentences.reshape(
                -1, self.sentence_length * self.chars_len)
            char_train = char_sentences[:num_train_samples]
            char_test = char_sentences[num_train_samples:]
            train_iters.append(TaggedTextSequence(steps=self.chars_len * self.sentence_length,
                                                  x=char_train))
            test_iters.append(TaggedTextSequence(steps=self.chars_len * self.sentence_length,
                                                 x=char_test))

        if len(train_iters) > 1:
            self._data_dict['train'] = MultiSequenceDataIterator(train_iters)
            self._data_dict['test'] = MultiSequenceDataIterator(test_iters)
        else:
            self._data_dict['train'] = train_iters[0]
            self._data_dict['test'] = test_iters[0]
        return self._data_dict

    @staticmethod
    def _sentences_to_ints(texts, lowercase=True):
        """
        convert text sentences into int id sequences. Word ids are sorted
        by frequency of appearance.
        return int sequences and vocabulary.
        """
        w_dict = {}
        for sen in texts:
            for w in sen:
                if lowercase:
                    w = w.lower()
                w_dict.update({w: w_dict.get(w, 0) + 1})
        int_to_word = [(i, word[0]) for i, word in
                       enumerate(sorted(w_dict.items(), key=lambda x: x[1], reverse=True))]
        vocab = {w: i for i, w in int_to_word}
        return [[vocab[w.lower()] if lowercase else vocab[w]
                 for w in sen] for sen in texts], vocab