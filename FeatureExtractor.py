from tqdm import tqdm
import pickle

from environment_aux import *
from collections import deque


def collect_features(output_filename, t_max, filenames):
    feature_matrix = []
    counter = 0

    featurer = PacketFeaturer(None)

    output_file = open(output_filename, 'w')

    try:
        for row in iterate_dataset(filenames):
            if counter % 50000 == 0:
                for item in feature_matrix:
                    output_file.write(' '.join([str(element) for element in item]) + '\n')
                feature_matrix = []
            if counter >= t_max:
                break
            featurer.update_packet_state(row)
            data = featurer.get_packet_features_pure(row).tolist()
            feature_matrix.append(np.asarray(data))
            if counter % 5000 == 0:
                d = featurer.fnum
                str_formatted = ' '.join(['{:^7.4f}' for _ in range(d)])
                str_formatted = '{:10d}  ' + str_formatted
                means = np.mean(feature_matrix, axis=0).tolist()
                str_formatted = str_formatted.format(*([counter] + means))
                sys.stdout.write('\r' + str_formatted)
                sys.stdout.flush()
            featurer.update_packet_info(row)
            counter += 1
        print ''
    except KeyboardInterrupt:
        pass
    for item in feature_matrix:
        output_file.write(' '.join([str(element) for element in item]) + '\n')
    output_file.close()


def print_mappings(mappings):
    mappings_flat = [item[0] for item in mappings] + [mappings[len(mappings) - 1][1]]
    pdata = ['A: {:5.3f}'] * len(mappings_flat[:min(17, len(mappings_flat))])
    pstr = ' | '.join(pdata)
    print pstr.format(*mappings_flat)


def print_statistics(statistics):
    stat_vector = []
    p_vector = []
    for mean, std in statistics[:min(10, len(statistics))]:
        stat_vector.append(mean)
        stat_vector.append(std)
        p_vector.append('M: {:5.3f} V: {:5.3f}')
    print ' | '.join(p_vector).format(*stat_vector)


class PacketFeaturer:
    def __init__(self, config):
        self.logical_time = 0
        self.real_time = 0
        names = ['timestamp', 'id', 'size', 'frequency', 'lasp_app', 'exp_recency', 'log_time', 'exp_log']
        fake_request = dict(zip(names, [1] * len(names)))
        self.fnum = len(self.get_packet_features_pure(fake_request))
        self.statistics = []
        self.bias = 0
        self.normalization_limit = 0
        print 'Real features', self.fnum

        self.preserved_logical_time = 0
        self.preserved_real_time = 0

        feature_names = ['size',
                         'frequency',
                         'gdsf',
                         'bhr',
                         'time recency',
                         'request recency',
                         'exponential time recency',
                         'exponential request recency']

        if config is not None:
            loading_failed = False
            self.normalization_limit = config['normalization limit']
            self.bias = config['bias']
            print 'Bias', self.bias, 'Normalization', self.normalization_limit
            if config['load']:
                try:
                    with open(config['filename'], 'r') as f:
                        data = pickle.load(f)
                        self.feature_mappings = data[0]
                        self.statistics = data[1]
                        cstep = data[2]
                        assert cstep == config['split step']
                    lindex = 0
                    if config['show stat']:
                        for i in range(self.fnum):
                            print 'Doing', feature_names[i]
                            print_mappings(self.feature_mappings[i])
                            print_statistics(self.statistics[lindex:lindex + len(self.feature_mappings[i])])
                            lindex += len(self.feature_mappings[i])
                except:
                    print 'Loading failed'
                    loading_failed = True
            if not config['load'] or loading_failed:
                data_raw = open(config['statistics'], 'r').readlines()[config['warmup']:]
                feature_set = np.zeros(shape=(len(data_raw), self.fnum))
                print 'Loading data'
                for i in tqdm(range(feature_set.shape[0])):
                    feature_set[i] = np.array([float(item) for item in data_raw[i].split(' ')[:self.fnum]])

                self.feature_mappings = []
                for i in range(self.fnum):
                    print 'Doing', feature_names[i]
                    self.feature_mappings.append(split_feature(feature_set[:, i], config['split step']))
                    statistics_arrays = []
                    for _ in range(len(self.feature_mappings[i])):
                        statistics_arrays.append(deque([]))
                    for item in tqdm(feature_set[:, i]):
                        _, feature_index = self.get_feature_vector(i, item)
                        statistics_arrays[feature_index].append(item)
                    statistics_vector = [(np.mean(item), np.std(item)) for item in statistics_arrays]
                    if config['show stat']:
                        print_mappings(self.feature_mappings[i])
                        print_statistics(statistics_vector)
                    self.statistics += statistics_vector
                if config['save']:
                    with open(config['filename'], 'w') as f:
                        pickle.dump([self.feature_mappings, self.statistics, config['split step']], f)
            self.dim = len(self.get_packet_features(fake_request))
        else:
            self.dim = 0

        print 'Features dim', self.dim

    def reset(self):
        self.logical_time = self.preserved_logical_time
        self.real_time = self.preserved_real_time

    def full_reset(self):
        self.logical_time = 0
        self.real_time = 0
        self.preserve()

    def preserve(self):
        self.preserved_logical_time = self.logical_time
        self.preserved_real_time = self.real_time

    def update_packet_state(self, packet):
        self.logical_time += 1
        self.real_time = packet['timestamp']

    def update_packet_info(self, packet):
        pass

    def observation_flag(self, packet):
        return 1 if packet['frequency'] != 1 else 0

    def get_packet_features_classical(self, packet):
        feature_vector = [float(packet['frequency']) / (float(packet['size'])),
                          packet['timestamp'],
                          self.observation_flag(packet),
                          float(packet['frequency']) * (float(packet['size']) / (1 + self.logical_time)),
                          float(packet['frequency']) / (1 + self.logical_time)]

        return np.asarray(feature_vector)

    def get_packet_features_pure(self, packet):
        feature_vector = []

        feature_vector.append(np.log(1 + float(packet['size'])))

        feature_vector.append(-np.log(1e-4 + float(packet['frequency']) / (1 + self.logical_time)))

        feature_vector.append(feature_vector[1] - feature_vector[0])

        feature_vector.append(feature_vector[1] + feature_vector[0])

        feature_vector.append(np.log(2 + float(self.real_time - packet['lasp_app'])))
        feature_vector.append(np.log(2 + float(self.logical_time - packet['log_time'])))
        feature_vector.append(np.log(2 + float(packet['exp_recency'])))
        feature_vector.append(np.log(2 + float(packet['exp_log'])))

        features = np.asarray(feature_vector)
        return features

    def get_feature_vector(self, feature_index, feature_value):
        tlen = len(self.feature_mappings[feature_index])
        addition = [0] * tlen
        counter = 0
        mlow = self.feature_mappings[feature_index][0][0]
        if feature_value < mlow:
            addition[counter] = feature_value
            return addition, counter
        mhigh = self.feature_mappings[feature_index][tlen - 1][1]
        if feature_value > mhigh:
            addition[tlen - 1] = feature_value
            counter = tlen - 1
            return addition, counter

        for low, up in self.feature_mappings[feature_index]:
            if low <= feature_value <= up:
                addition[counter] = feature_value
                return addition, counter
            counter += 1

        assert False

    def get_packet_features_from_pure(self, pure_features, return_statistics=False):
        result = []
        statistics = []
        for i in range(self.fnum):
            feature_vector, index = self.get_feature_vector(i, pure_features[i])
            stat_vector = [0] * len(feature_vector)
            stat_vector[index] = 1
            statistics += stat_vector
            result += feature_vector
        result_features = np.asarray(result)
        if return_statistics:
            return result_features, statistics
        return result_features

    def apply_statistics(self, result_features, statistics):
        result = [0] * len(result_features)
        for i in range(len(result_features)):
            if statistics[i] != 0:
                result[i] = self.bias + min(1, max(-1, (result_features[i] - self.statistics[i][0]) / (
                        1e-4 + self.normalization_limit * self.statistics[i][1])))
        return np.asarray(result)

    def get_packet_features(self, packet):
        feature_vector = self.get_packet_features_pure(packet)
        corrected_features, statistics = self.get_packet_features_from_pure(feature_vector, return_statistics=True)
        return self.apply_statistics(corrected_features, statistics)
