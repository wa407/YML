from models import ModelBase
# from models import TrainingDataType
import numpy as np
import cv2

# from nnlib import DSSIMMSEMaskLoss
# from nnlib import conv
# from nnlib import upscale
from facelib import FaceType

import numpy as np

from nnlib import nnlib
from models import ModelBase
from facelib import FaceType
from samplelib import *
from interact import interact as io

import keras

def downscale(dim):
    def func(x):
        return keras.layers.LeakyReLU(0.1)(keras.layers.Conv2D(dim, 5, strides=2, padding='same')(x))

    return func


def upscale(dim):
    def func(x):
        return nnlib.PixelShuffler()(keras.layers.LeakyReLU(0.1)(keras.layers.Conv2D(dim * 4, 3, strides=1, padding='same')(x)))

    return func


class Model(ModelBase):
    encoderH5 = 'encoder.h5'
    decoderMaskH5 = 'decoderMask.h5'
    decoderCommonAH5 = 'decoderCommonA.h5'
    decoderCommonBH5 = 'decoderCommonB.h5'
    decoderRGBH5 = 'decoderRGB.h5'
    decoderBWH5 = 'decoderBW.h5'
    inter_BH5 = 'inter_B.h5'
    inter_AH5 = 'inter_A.h5'

    # override
    def onInitialize(self, batch_size=-1, **in_options):
        # if self.gpu_total_vram_gb < 5:
        #     raise Exception('Sorry, this model works only on 5GB+ GPU')

        self.batch_size = batch_size
        if self.batch_size <= 0:
            self.batch_size = 4
            # if self.gpu_total_vram_gb == 5:
            #     self.batch_size = 4
            # elif self.gpu_total_vram_gb == 6:
            #     self.batch_size = 4
            # elif self.gpu_total_vram_gb < 12:
            #     self.batch_size = 16
            # else:
            #     self.batch_size = 32

        ae_input_layer = self.keras.layers.Input(shape=(256, 256, 3))
        mask_layer = self.keras.layers.Input(shape=(256, 256, 1))  # same as output

        self.encoder = self.Encoder(ae_input_layer)
        self.decoderMask = self.DecoderMask()
        self.decoderCommonA = self.DecoderCommon()
        self.decoderCommonB = self.DecoderCommon()
        self.decoderRGB = self.DecoderRGB()
        self.decoderBW = self.DecoderBW()
        self.inter_A = self.Intermediate()
        self.inter_B = self.Intermediate()

        if not self.is_first_run():
            self.load_weights_safe([[self.encoder, self.encoderH5],
                                    [self.decoderMask, self.decoderMaskH5],
                                    [self.decoderCommonA, self.decoderCommonAH5],
                                    [self.decoderCommonB, self.decoderCommonBH5],
                                    [self.decoderRGB, self.decoderRGBH5],
                                    [self.decoderBW, self.decoderBWH5],
                                    [self.inter_A, self.inter_AH5],
                                    [self.inter_B, self.inter_BH5]])
            # self.encoder.load_weights(self.get_strpath_storage_for_file(self.encoderH5))
            # self.decoderMask.load_weights(self.get_strpath_storage_for_file(self.decoderMaskH5))
            # self.decoderCommonA.load_weights(self.get_strpath_storage_for_file(self.decoderCommonAH5))
            # self.decoderCommonB.load_weights(self.get_strpath_storage_for_file(self.decoderCommonBH5))
            # self.decoderRGB.load_weights(self.get_strpath_storage_for_file(self.decoderRGBH5))
            # self.decoderBW.load_weights(self.get_strpath_storage_for_file(self.decoderBWH5))
            # self.inter_A.load_weights(self.get_strpath_storage_for_file(self.inter_AH5))
            # self.inter_B.load_weights(self.get_strpath_storage_for_file(self.inter_BH5))

        code = self.encoder(ae_input_layer)
        A = self.inter_A(code)
        B = self.inter_B(code)

        inter_A_A = self.keras.layers.Concatenate()([A, A])
        inter_B_A = self.keras.layers.Concatenate()([B, A])

        x1, m1 = self.decoderCommonA(inter_A_A)
        x2, m2 = self.decoderCommonA(inter_A_A)
        self.autoencoder_src = self.keras.models.Model([ae_input_layer, mask_layer],
                                                       [self.decoderBW(self.keras.layers.Concatenate()([x1, x2])),
                                                        self.decoderMask(self.keras.layers.Concatenate()([m1, m2]))
                                                        ])

        x1, m1 = self.decoderCommonA(inter_A_A)
        x2, m2 = self.decoderCommonB(inter_A_A)
        self.autoencoder_src_RGB = self.keras.models.Model([ae_input_layer, mask_layer],
                                                           [self.decoderRGB(self.keras.layers.Concatenate()([x1, x2])),
                                                            self.decoderMask(self.keras.layers.Concatenate()([m1, m2]))
                                                            ])

        x1, m1 = self.decoderCommonA(inter_B_A)
        x2, m2 = self.decoderCommonB(inter_B_A)
        self.autoencoder_dst = self.keras.models.Model([ae_input_layer, mask_layer],
                                                       [self.decoderRGB(self.keras.layers.Concatenate()([x1, x2])),
                                                        self.decoderMask(self.keras.layers.Concatenate()([m1, m2]))
                                                        ])

        # if self.is_training_mode:
            # self.autoencoder_src, self.autoencoder_dst = self.to_multi_gpu_model_if_possible(
            #     [self.autoencoder_src, self.autoencoder_dst])

        optimizer = self.keras.optimizers.Adam(lr=5e-5, beta_1=0.5, beta_2=0.999)
        # dssimloss = nnlib.DSSIMMSEMaskLoss(self.tf)([mask_layer])
        dssimloss = nnlib.DSSIMMSEMaskLoss(mask_layer)
        self.autoencoder_src.compile(optimizer=optimizer, loss=[dssimloss, 'mse'])
        self.autoencoder_dst.compile(optimizer=optimizer, loss=[dssimloss, 'mse'])

        if self.is_training_mode:
            # from models import TrainingDataGenerator
            # f = TrainingDataGenerator.SampleTypeFlags
            f = SampleProcessor.TypeFlags
            self.set_training_data_generators([
                SampleGeneratorFace(self.training_data_src_path, debug=self.is_debug(), batch_size=self.batch_size,
                                    output_sample_types=[[f.WARPED_TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_GGG, 256],
                                                         [f.TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_G, 256],
                                                         [
                                                             f.TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_M | f.FACE_MASK_FULL,
                                                             256],
                                                         [f.TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_GGG, 256]]),

                SampleGeneratorFace(self.training_data_dst_path, debug=self.is_debug(), batch_size=self.batch_size,
                                    output_sample_types=[[f.WARPED_TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_BGR, 256],
                                                         [f.TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_BGR, 256],
                                                         [
                                                             f.TRANSFORMED | f.FACE_ALIGN_FULL | f.MODE_M | f.FACE_MASK_FULL,
                                                             256]])
            ])
            # self.set_training_data_generators ([
            #         TrainingDataGenerator(self, TrainingDataType.FACE_SRC,  batch_size=self.batch_size, output_sample_types=[ [f.WARPED_TRANSFORMED | f.FULL_FACE | f.MODE_GGG, 256], [f.TRANSFORMED | f.FULL_FACE | f.MODE_G  , 256], [f.TRANSFORMED | f.FULL_FACE | f.MODE_M | f.MASK_FULL, 256], [f.TRANSFORMED | f.FULL_FACE | f.MODE_GGG, 256] ], random_flip=True ),
            #         TrainingDataGenerator(self, TrainingDataType.FACE_DST,  batch_size=self.batch_size, output_sample_types=[ [f.WARPED_TRANSFORMED | f.FULL_FACE | f.MODE_BGR, 256], [f.TRANSFORMED | f.FULL_FACE | f.MODE_BGR, 256], [f.TRANSFORMED | f.FULL_FACE | f.MODE_M | f.MASK_FULL, 256]], random_flip=True )
            #     ])

    # override
    def onSave(self):
        self.save_weights_safe([[self.encoder, self.encoderH5],
                                [self.decoderMask, self.decoderMaskH5],
                                [self.decoderCommonA, self.decoderCommonAH5],
                                [self.decoderCommonB, self.decoderCommonBH5],
                                [self.decoderRGB, self.decoderRGBH5],
                                [self.decoderBW, self.decoderBWH5],
                                [self.inter_A, self.inter_AH5],
                                [self.inter_B, self.inter_BH5]])

    # override
    def onTrainOneIter(self, sample, generators_list):
        warped_src, target_src, target_src_mask, target_src_GGG = sample[0]
        warped_dst, target_dst, target_dst_mask = sample[1]

        loss_src = self.autoencoder_src.train_on_batch([warped_src, target_src_mask], [target_src, target_src_mask])
        loss_dst = self.autoencoder_dst.train_on_batch([warped_dst, target_dst_mask], [target_dst, target_dst_mask])

        return (('loss_src', loss_src[0]), ('loss_dst', loss_dst[0]))

        # override

    def onGetPreview(self, sample):
        test_A = sample[0][3][0:2]  # first 4 samples
        test_A_m = sample[0][2][0:2]  # first 4 samples
        test_B = sample[1][1][0:2]
        test_B_m = sample[1][2][0:2]

        AA, mAA = self.autoencoder_src.predict([test_A, test_A_m])
        AB, mAB = self.autoencoder_src_RGB.predict([test_B, test_B_m])
        BB, mBB = self.autoencoder_dst.predict([test_B, test_B_m])

        mAA = np.repeat(mAA, (3,), -1)
        mAB = np.repeat(mAB, (3,), -1)
        mBB = np.repeat(mBB, (3,), -1)

        st = []
        for i in range(0, len(test_A)):
            st.append(np.concatenate((
                np.repeat(np.expand_dims(test_A[i, :, :, 0], -1), (3,), -1),
                np.repeat(AA[i], (3,), -1),
                # mAA[i],
                test_B[i, :, :, 0:3],
                BB[i],
                # mBB[i],
                AB[i],
                # mAB[i]
            ), axis=1))

        return [('src, dst, src->dst', np.concatenate(st, axis=0))]

    def predictor_func(self, face):
        face_128_bgr = face[..., 0:3]
        face_128_mask = np.expand_dims(face[..., -1], -1)

        x, mx = self.autoencoder_src_RGB.predict([np.expand_dims(face_128_bgr, 0), np.expand_dims(face_128_mask, 0)])
        x, mx = x[0], mx[0]

        return np.concatenate((x, mx), -1)

    # override
    def get_converter(self, **in_options):
        from converters import ConverterMasked

        if 'erode_mask_modifier' not in in_options.keys():
            in_options['erode_mask_modifier'] = 0
        in_options['erode_mask_modifier'] += 30

        if 'blur_mask_modifier' not in in_options.keys():
            in_options['blur_mask_modifier'] = 0

        return ConverterMasked(self.predictor_func, predictor_input_size=256, output_size=256, face_type=FaceType.FULL,
                               clip_border_mask_per=0.046875, **in_options)

    def Encoder(self, input_layer, ):
        x = input_layer
        x = downscale(64)(x)
        x = downscale(128)(x)
        x = downscale(256)(x)
        x = downscale(512)(x)
        # x = downscale(self.keras, x, 64)
        # x = downscale(self.keras, x, 128)
        # x = downscale(self.keras, x, 256)
        # x = downscale(self.keras, x, 512)
        x = self.keras.layers.Flatten()(x)
        return self.keras.models.Model(input_layer, x)

    def Intermediate(self):
        input_layer = self.keras.layers.Input(shape=(None, 16 * 16 * 512))
        x = input_layer
        x = self.keras.layers.Dense(128)(x)
        x = self.keras.layers.Dense(16 * 16 * 256)(x)
        x = self.keras.layers.Reshape((16, 16, 256))(x)
        x = upscale(256)(x)
        # x = upscale(self.keras, x, 256)
        return self.keras.models.Model(input_layer, x)

    def DecoderCommon(self):
        input_ = self.keras.layers.Input(shape=(32, 32, 512))
        x = input_
        # x = upscale(self.keras, x, 512)
        # x = upscale(self.keras, x, 256)
        # x = upscale(self.keras, x, 128)
        x = upscale(512)(x)
        x = upscale(256)(x)
        x = upscale(128)(x)

        y = input_
        # y = upscale(self.keras, y, 256)
        # y = upscale(self.keras, y, 128)
        # y = upscale(self.keras, y, 64)
        y = upscale(256)(y)
        y = upscale(128)(y)
        y = upscale(64)(y)

        return self.keras.models.Model(input_, [x, y])

    def DecoderRGB(self):
        input_ = self.keras.layers.Input(shape=(128, 128, 256))
        x = input_
        x = self.keras.layers.convolutional.Conv2D(3, kernel_size=5, padding='same', activation='sigmoid')(x)
        return self.keras.models.Model(input_, [x])

    def DecoderBW(self):
        input_ = self.keras.layers.Input(shape=(128, 128, 256))
        x = input_
        x = self.keras.layers.convolutional.Conv2D(1, kernel_size=5, padding='same', activation='sigmoid')(x)
        return self.keras.models.Model(input_, [x])

    def DecoderMask(self):
        input_ = self.keras.layers.Input(shape=(128, 128, 128))
        y = input_
        y = self.keras.layers.convolutional.Conv2D(1, kernel_size=5, padding='same', activation='sigmoid')(y)
        return self.keras.models.Model(input_, [y])
