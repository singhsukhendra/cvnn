import six
import functools
import tensorflow as tf
from tensorflow.keras.layers import Layer
from tensorflow.python.keras import initializers
from tensorflow.python.keras import regularizers
from tensorflow.python.keras import activations
from tensorflow.python.keras import constraints
from tensorflow.python.framework import tensor_shape
from tensorflow.python.keras.utils import conv_utils
from tensorflow.python.ops import array_ops
from tensorflow.python.keras.engine.input_spec import InputSpec
from tensorflow.python.ops import nn
from tensorflow.python.ops import nn_ops
# Own modules
from cvnn.layers.core import ComplexLayer
from cvnn.initializers import ComplexGlorotUniform, Zeros
from cvnn import logger
from cvnn.layers.core import DEFAULT_COMPLEX_TYPE


class ComplexConv(Layer, ComplexLayer):
    """
    Almost exact copy of
        https://github.com/tensorflow/tensorflow/blob/v2.4.0/tensorflow/python/keras/layers/convolutional.py#L52
    Abstract N-D complex convolution layer (private, used as implementation base).
      This layer creates a convolution kernel that is convolved
      (actually cross-correlated) with the layer input to produce a tensor of
      outputs. If `use_bias` is True (and a `bias_initializer` is provided),
      a bias vector is created and added to the outputs. Finally, if
      `activation` is not `None`, it is applied to the outputs as well.
      Note: layer attributes cannot be modified after the layer has been called
      once (except the `trainable` attribute).
      Arguments:
        rank: An integer, the rank of the convolution, e.g. "2" for 2D convolution.
        filters: Integer, the dimensionality of the output space (i.e. the number
          of filters in the convolution).
        kernel_size: An integer or tuple/list of n integers, specifying the
          length of the convolution window.
        strides: An integer or tuple/list of n integers,
          specifying the stride length of the convolution.
          Specifying any stride value != 1 is incompatible with specifying
          any `dilation_rate` value != 1.
        padding: One of `"valid"`,  `"same"`, or `"causal"` (case-insensitive).
          `"valid"` means no padding. `"same"` results in padding evenly to
          the left/right or up/down of the input such that output has the same
          height/width dimension as the input. `"causal"` results in causal
          (dilated) convolutions, e.g. `output[t]` does not depend on `input[t+1:]`.
        data_format: A string, one of `channels_last` (default) or `channels_first`.
          The ordering of the dimensions in the inputs.
          `channels_last` corresponds to inputs with shape
          `(batch_size, ..., channels)` while `channels_first` corresponds to
          inputs with shape `(batch_size, channels, ...)`.
        dilation_rate: An integer or tuple/list of n integers, specifying
          the dilation rate to use for dilated convolution.
          Currently, specifying any `dilation_rate` value != 1 is
          incompatible with specifying any `strides` value != 1.
        groups: A positive integer specifying the number of groups in which the
          input is split along the channel axis. Each group is convolved
          separately with `filters / groups` filters. The output is the
          concatenation of all the `groups` results along the channel axis.
          Input channels and `filters` must both be divisible by `groups`.
        activation: Activation function to use.
          If you don't specify anything, no activation is applied.
        use_bias: Boolean, whether the layer uses a bias.
        kernel_initializer: An initializer for the convolution kernel.
        bias_initializer: An initializer for the bias vector. If None, the default
          initializer will be used.
        kernel_regularizer: Optional regularizer for the convolution kernel.
            ATTENTION: Not yet implemented! This parameter will have no effect.
        bias_regularizer: Optional regularizer for the bias vector.
            ATTENTION: Not yet implemented! This parameter will have no effect.
        activity_regularizer: Optional regularizer function for the output.
        kernel_constraint: Optional projection function to be applied to the
            kernel after being updated by an `Optimizer` (e.g. used to implement
            norm constraints or value constraints for layer weights). The function
            must take as input the unprojected variable and must return the
            projected variable (which must have the same shape). Constraints are
            not safe to use when doing asynchronous distributed training.
        bias_constraint: Optional projection function to be applied to the
            bias after being updated by an `Optimizer`.
      """

    def __init__(self, rank, filters, kernel_size, dtype, strides=1, padding='valid', data_format=None, dilation_rate=1,
                 groups=1, activation=None, use_bias=True,
                 kernel_initializer=ComplexGlorotUniform(), bias_initializer=Zeros(),
                 kernel_regularizer=None, bias_regularizer=None,  # TODO: Not yet working
                 activity_regularizer=None, kernel_constraint=None, bias_constraint=None,
                 trainable=True, name=None, conv_op=None, **kwargs):
        if kernel_regularizer is not None or bias_regularizer is not None:
            logger.warning(f"Sorry, regularizers are not implemented yet, this parameter will take no effect")
        super(ComplexConv, self).__init__(
            trainable=trainable,
            name=name,
            activity_regularizer=regularizers.get(activity_regularizer),
            **kwargs)
        self.rank = rank
        self.my_dtype = tf.dtypes.as_dtype(dtype)
        # I use no default dtype to make sure I don't forget to give it to my ComplexConv layers
        if isinstance(filters, float):
            filters = int(filters)
        self.filters = filters
        self.groups = groups or 1
        self.kernel_size = conv_utils.normalize_tuple(
            kernel_size, rank, 'kernel_size')
        self.strides = conv_utils.normalize_tuple(strides, rank, 'strides')
        self.padding = conv_utils.normalize_padding(padding)
        self.data_format = conv_utils.normalize_data_format(data_format)
        self.dilation_rate = conv_utils.normalize_tuple(
            dilation_rate, rank, 'dilation_rate')

        self.activation = activations.get(activation)
        self.use_bias = use_bias

        self.kernel_initializer = initializers.get(kernel_initializer)
        self.bias_initializer = initializers.get(bias_initializer)
        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.bias_regularizer = regularizers.get(bias_regularizer)
        self.kernel_constraint = constraints.get(kernel_constraint)
        self.bias_constraint = constraints.get(bias_constraint)
        self.input_spec = InputSpec(min_ndim=self.rank + 2)

        self._validate_init()
        self._is_causal = self.padding == 'causal'
        self._channels_first = self.data_format == 'channels_first'
        self._tf_data_format = conv_utils.convert_data_format(
            self.data_format, self.rank + 2)

    def _validate_init(self):
        if self.filters is not None and self.filters % self.groups != 0:
            raise ValueError(
                'The number of filters must be evenly divisible by the number of '
                'groups. Received: groups={}, filters={}'.format(
                    self.groups, self.filters))

        if not all(self.kernel_size):
            raise ValueError('The argument `kernel_size` cannot contain 0(s). '
                             'Received: %s' % (self.kernel_size,))

        if (self.padding == 'causal' and not isinstance(self, (ComplexConv1D))):
            raise ValueError('Causal padding is only supported for `Conv1D`'
                             'and `SeparableConv1D`.')

    def build(self, input_shape):
        input_shape = tensor_shape.TensorShape(input_shape)
        input_channel = self._get_input_channel(input_shape)
        if input_channel % self.groups != 0:
            raise ValueError(
                f'The number of input channels must be evenly divisible by the number '
                f'of groups. Received groups={self.groups}, but the input has {input_channel} channels '
                f'(full input shape is {input_shape}).')
        kernel_shape = self.kernel_size + (input_channel // self.groups, self.filters)
        if self.my_dtype.is_complex:
            self.kernel_r = tf.Variable(
                initial_value=self.kernel_initializer(shape=kernel_shape, dtype=self.my_dtype),
                name='kernel_r',
                constraint=self.kernel_constraint,
                trainable=True
            )  # TODO: regularizer=self.kernel_regularizer,
            self.kernel_i = tf.Variable(
                initial_value=self.kernel_initializer(shape=kernel_shape, dtype=self.my_dtype),
                name='kernel_i',
                constraint=self.kernel_constraint,
                trainable=True
            )  # TODO: regularizer=self.kernel_regularizer
            if self.use_bias:
                self.bias_r = tf.Variable(
                    initial_value=self.bias_initializer(shape=(self.filters,), dtype=self.my_dtype),
                    name='bias_r',
                    trainable=True
                )
                self.bias_i = tf.Variable(
                    initial_value=self.bias_initializer(shape=(self.filters,), dtype=self.my_dtype),
                    name='bias_i',
                    constraint=self.bias_constraint,
                    trainable=True
                )  # TODO: regularizer=self.bias_regularizer
        else:
            self.kernel = self.add_weight(
                name='kernel',
                shape=kernel_shape,
                initializer=self.kernel_initializer,
                regularizer=self.kernel_regularizer,
                constraint=self.kernel_constraint,
                trainable=True,
                dtype=self.my_dtype)
            if self.use_bias:
                self.bias = self.add_weight(
                    name='bias',
                    shape=(self.filters,),
                    initializer=self.bias_initializer,
                    regularizer=self.bias_regularizer,
                    constraint=self.bias_constraint,
                    trainable=True,
                    dtype=self.my_dtype)
        if not self.use_bias:
            self.bias = None
        channel_axis = self._get_channel_axis()
        self.input_spec = InputSpec(min_ndim=self.rank + 2,
                                    axes={channel_axis: input_channel})

        # Convert Keras formats to TF native formats.
        if self.padding == 'causal':
            tf_padding = 'VALID'  # Causal padding handled in `call`.
        elif isinstance(self.padding, six.string_types):
            tf_padding = self.padding.upper()
        else:
            tf_padding = self.padding
        tf_dilations = list(self.dilation_rate)
        tf_strides = list(self.strides)

        tf_op_name = self.__class__.__name__
        if tf_op_name == 'Conv1D':
            tf_op_name = 'conv1d'  # Backwards compat.

        self._convolution_op = functools.partial(
            nn_ops.convolution_v2,
            strides=tf_strides,
            padding=tf_padding,
            dilations=tf_dilations,
            data_format=self._tf_data_format,
            name=tf_op_name)
        self.built = True

    def call(self, inputs):
        """
        Calls convolution, this function is divided in 4:
            1. Input parser/verification
            2. Convolution
            3. Bias
            4. Activation Function
        :returns: A tensor of rank 4+ representing `activation(conv2d(inputs, kernel) + bias)`.
        """
        if inputs.dtype != self.my_dtype:
            tf.print(f"WARNING: {self.name} - Expected input to be {self.my_dtype}, but received {inputs.dtype}.")
            if self.my_dtype.is_complex and inputs.dtype.is_floating:
                tf.print("\tThis is normally fixed using ComplexInput() "
                         "at the start (tf casts input automatically to real).")
            inputs = tf.cast(inputs, self.my_dtype)
        if self._is_causal:  # Apply causal padding to inputs for Conv1D.
            inputs = array_ops.pad(inputs, self._compute_causal_padding(inputs))
        # Convolution
        inputs_r = tf.math.real(inputs)
        inputs_i = tf.math.imag(inputs)
        if self.my_dtype.is_complex:
            kernel_r = self.kernel_r
            kernel_i = self.kernel_i
            if self.use_bias:
                bias = tf.complex(self.bias_r, self.bias_i)
        else:
            kernel_r = tf.math.real(self.kernel)
            kernel_i = tf.math.imag(self.kernel)
            if self.use_bias:
                bias = self.bias
        real_outputs = self._convolution_op(inputs_r, kernel_r) - self._convolution_op(inputs_i, kernel_i)
        imag_outputs = self._convolution_op(inputs_r, kernel_i) + self._convolution_op(inputs_i, kernel_r)
        outputs = tf.cast(tf.complex(real_outputs, imag_outputs), dtype=self.my_dtype)
        # Add bias
        if self.use_bias:
            output_rank = outputs.shape.rank
            if self.rank == 1 and self._channels_first:
                # nn.bias_add does not accept a 1D input tensor.
                bias = array_ops.reshape(bias, (1, self.filters, 1))
                outputs += bias
            else:
                # Handle multiple batch dimensions.
                if output_rank is not None and output_rank > 2 + self.rank:

                    def _apply_fn(o):
                        # TODO: Will this bias be visible? Horrible
                        return nn.bias_add(o, bias, data_format=self._tf_data_format)

                    outputs = nn_ops.squeeze_batch_dims(
                        outputs, _apply_fn, inner_rank=self.rank + 1)
                else:
                    outputs = nn.bias_add(
                        outputs, bias, data_format=self._tf_data_format)
        # Activation function
        if self.activation is not None:
            outputs = self.activation(outputs)
        return outputs

    def _spatial_output_shape(self, spatial_input_shape):
        return [
            conv_utils.conv_output_length(
                length,
                self.kernel_size[i],
                padding=self.padding,
                stride=self.strides[i],
                dilation=self.dilation_rate[i])
            for i, length in enumerate(spatial_input_shape)
        ]

    def compute_output_shape(self, input_shape):
        input_shape = tensor_shape.TensorShape(input_shape).as_list()
        batch_rank = len(input_shape) - self.rank - 1
        if self.data_format == 'channels_last':
            return tensor_shape.TensorShape(
                input_shape[:batch_rank]
                + self._spatial_output_shape(input_shape[batch_rank:-1])
                + [self.filters])
        else:
            return tensor_shape.TensorShape(
                input_shape[:batch_rank] + [self.filters] +
                self._spatial_output_shape(input_shape[batch_rank + 1:]))

    def _recreate_conv_op(self, inputs):  # pylint: disable=unused-argument
        return False

    def get_config(self):
        config = {
            'filters':
                self.filters,
            'kernel_size':
                self.kernel_size,
            'strides':
                self.strides,
            'padding':
                self.padding,
            'data_format':
                self.data_format,
            'dilation_rate':
                self.dilation_rate,
            'groups':
                self.groups,
            'activation':
                activations.serialize(self.activation),
            'use_bias':
                self.use_bias,
            'kernel_initializer':
                initializers.serialize(self.kernel_initializer),
            'bias_initializer':
                initializers.serialize(self.bias_initializer),
            'kernel_regularizer':
                regularizers.serialize(self.kernel_regularizer),
            'bias_regularizer':
                regularizers.serialize(self.bias_regularizer),
            'activity_regularizer':
                regularizers.serialize(self.activity_regularizer),
            'kernel_constraint':
                constraints.serialize(self.kernel_constraint),
            'bias_constraint':
                constraints.serialize(self.bias_constraint)
        }
        base_config = super(ComplexConv, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def _compute_causal_padding(self, inputs):
        """Calculates padding for 'causal' option for 1-d conv layers."""
        left_pad = self.dilation_rate[0] * (self.kernel_size[0] - 1)
        if getattr(inputs.shape, 'ndims', None) is None:
            batch_rank = 1
        else:
            batch_rank = len(inputs.shape) - 2
        if self.data_format == 'channels_last':
            causal_padding = [[0, 0]] * batch_rank + [[left_pad, 0], [0, 0]]
        else:
            causal_padding = [[0, 0]] * batch_rank + [[0, 0], [left_pad, 0]]
        return causal_padding

    def _get_channel_axis(self):
        if self.data_format == 'channels_first':
            return -1 - self.rank
        else:
            return -1

    def _get_input_channel(self, input_shape):
        channel_axis = self._get_channel_axis()
        if input_shape.dims[channel_axis].value is None:
            raise ValueError('The channel dimension of the inputs '
                             'should be defined. Found `None`.')
        return int(input_shape[channel_axis])

    def _get_padding_op(self):
        if self.padding == 'causal':
            op_padding = 'valid'
        else:
            op_padding = self.padding
        if not isinstance(op_padding, (list, tuple)):
            op_padding = op_padding.upper()
        return op_padding

    def get_real_equivalent(self):
        # TODO: Shall I check it's not already complex?
        return ComplexConv(rank=self.rank, filters=self.filters, kernel_size=self.kernel_size,
                           dtype=self.my_dtype.real_dtype, strides=self.strides, padding=self.padding,
                           data_format=self.data_format, dilation_rate=self.dilation_rate, groups=self.groups,
                           activation=self.activation, use_bias=self.use_bias,
                           kernel_initializer=self.kernel_initializer, bias_initializer=self.bias_initializer,
                           kernel_regularizer=self.kernel_regularizer, bias_regularizer=self.bias_regularizer,
                           activity_regularizer=self.activity_regularizer, kernel_constraint=self.kernel_constraint,
                           bias_constraint=self.bias_constraint, trainable=self.trainable,
                           name=self.name + "_real_equiv")


class ComplexConv1D(ComplexConv):
    def __init__(self,
                 filters,
                 kernel_size,
                 strides=1,
                 padding='valid', dtype=DEFAULT_COMPLEX_TYPE,
                 data_format='channels_last',
                 dilation_rate=1,
                 groups=1,
                 activation=None,
                 use_bias=True,
                 kernel_initializer=ComplexGlorotUniform(),
                 bias_initializer=Zeros(),
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(ComplexConv1D, self).__init__(
            rank=1, dtype=dtype,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            groups=groups,
            activation=activations.get(activation),
            use_bias=use_bias,
            kernel_initializer=initializers.get(kernel_initializer),
            bias_initializer=initializers.get(bias_initializer),
            kernel_regularizer=regularizers.get(kernel_regularizer),
            bias_regularizer=regularizers.get(bias_regularizer),
            activity_regularizer=regularizers.get(activity_regularizer),
            kernel_constraint=constraints.get(kernel_constraint),
            bias_constraint=constraints.get(bias_constraint),
            **kwargs)


class ComplexConv2D(ComplexConv):
    """2D convolution layer (e.g. spatial convolution over images).
      This layer creates a convolution kernel that is convolved
      with the layer input to produce a tensor of outputs.
      If `use_bias` is True, a bias vector is created and added to the outputs.
      Finally, if `activation` is not `None`, it is applied to the outputs as well.
      When using this layer as the first layer in a model, provide the keyword argument `input_shape`
      (tuple of integers, does not include the sample axis),
      e.g. `input_shape=(128, 128, 3)` for 128x128 RGB pictures in `data_format="channels_last"`.
      Input shape:
        4+D tensor with shape: `batch_shape + (channels, rows, cols)` if
          `data_format='channels_first'`
        or 4+D tensor with shape: `batch_shape + (rows, cols, channels)` if
          `data_format='channels_last'`.
      Output shape:
        4+D tensor with shape: `batch_shape + (filters, new_rows, new_cols)` if
        `data_format='channels_first'` or 4+D tensor with shape: `batch_shape +
          (new_rows, new_cols, filters)` if `data_format='channels_last'`.  `rows`
          and `cols` values might have changed due to padding.
      Returns:
        A tensor of rank 4+ representing
        `activation(conv2d(inputs, kernel) + bias)`.
      Raises:
        ValueError: if `padding` is `"causal"`.
        ValueError: when both `strides > 1` and `dilation_rate > 1`.
      """

    def __init__(self, filters, kernel_size, strides=(1, 1), padding='valid', data_format=None, dilation_rate=(1, 1),
                 groups=1, activation=None, use_bias=True, dtype=DEFAULT_COMPLEX_TYPE,
                 kernel_initializer=ComplexGlorotUniform(), bias_initializer=Zeros(),
                 kernel_regularizer=None, bias_regularizer=None, activity_regularizer=None,
                 kernel_constraint=None, bias_constraint=None, **kwargs):
        """
        :param filters: Integer, the dimensionality of the output space (i.e. the number of output filters in the convolution).
        :param kernel_size: An integer or tuple/list of 2 integers, specifying the height
            and width of the 2D convolution window. Can be a single integer to specify
            the same value for all spatial dimensions.
        :param strides: An integer or tuple/list of 2 integers, specifying the strides of
            the convolution along the height and width. Can be a single integer to
            specify the same value for all spatial dimensions. Specifying any stride
            value != 1 is incompatible with specifying any `dilation_rate` value != 1.
        :param padding: one of `"valid"` or `"same"` (case-insensitive).
            `"valid"` means no padding. `"same"` results in padding evenly to
            the left/right or up/down of the input such that output has the same
            height/width dimension as the input.
        :param data_format: A string, one of `channels_last` (default) or `channels_first`.
            The ordering of the dimensions in the inputs. `channels_last` corresponds
            to inputs with shape `(batch_size, height, width, channels)` while
            `channels_first` corresponds to inputs with shape `(batch_size, channels,
            height, width)`. It defaults to the `image_data_format` value found in
            your Keras config file at `~/.keras/keras.json`. If you never set it, then
            it will be `channels_last`.
        :param dilation_rate: an integer or tuple/list of 2 integers, specifying the
            dilation rate to use for dilated convolution. Can be a single integer to
            specify the same value for all spatial dimensions. Currently, specifying
            any `dilation_rate` value != 1 is incompatible with specifying any stride
            value != 1.
        :param groups: A positive integer specifying the number of groups in which the
            input is split along the channel axis. Each group is convolved separately
            with `filters / groups` filters. The output is the concatenation of all
            the `groups` results along the channel axis. Input channels and `filters`
            must both be divisible by `groups`.
        :param activation: Activation function to use. If you don't specify anything, no activation is applied.
            For complex :code:`dtype`, this must be a :code:`cvnn.activations` module.
        :param use_bias: Boolean, whether the layer uses a bias vector.
        :param kernel_initializer: Initializer for the `kernel` weights matrix (see `keras.initializers`).
        :param bias_initializer: Initializer for the bias vector (see `keras.initializers`).
        :param kernel_regularizer: Regularizer function applied to the `kernel` weights matrix (see `keras.regularizers`).
        :param bias_regularizer: Regularizer function applied to the bias vector (see `keras.regularizers`).
        :param activity_regularizer: Regularizer function applied to the output of the layer (its "activation") (see `keras.regularizers`).
        :param kernel_constraint: Constraint function applied to the kernel matrix (see `keras.constraints`).
        :param bias_constraint: Constraint function applied to the bias vector (see `keras.constraints`).
        """
        super(ComplexConv2D, self).__init__(
            rank=2, dtype=dtype,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            groups=groups,
            activation=activations.get(activation),
            use_bias=use_bias,
            kernel_initializer=initializers.get(kernel_initializer),
            bias_initializer=initializers.get(bias_initializer),
            kernel_regularizer=regularizers.get(kernel_regularizer),
            bias_regularizer=regularizers.get(bias_regularizer),
            activity_regularizer=regularizers.get(activity_regularizer),
            kernel_constraint=constraints.get(kernel_constraint),
            bias_constraint=constraints.get(bias_constraint),
            **kwargs)


class ComplexConv3D(ComplexConv):
    """3D convolution layer (e.g. spatial convolution over volumes).
      This layer creates a convolution kernel that is convolved
      with the layer input to produce a tensor of
      outputs. If `use_bias` is True,
      a bias vector is created and added to the outputs. Finally, if
      `activation` is not `None`, it is applied to the outputs as well.
      When using this layer as the first layer in a model,
      provide the keyword argument `input_shape`
      (tuple of integers, does not include the sample axis),
      e.g. `input_shape=(128, 128, 128, 1)` for 128x128x128 volumes
      with a single channel,
      in `data_format="channels_last"`.
      Examples:
      >>> # The inputs are 28x28x28 volumes with a single channel, and the
      >>> # batch size is 4
      >>> input_shape =(4, 28, 28, 28, 1)
      >>> x = tf.random.normal(input_shape)
      >>> y = tf.keras.layers.Conv3D(
      ... 2, 3, activation='relu', input_shape=input_shape[1:])(x)
      >>> print(y.shape)
      (4, 26, 26, 26, 2)
      >>> # With extended batch shape [4, 7], e.g. a batch of 4 videos of 3D frames,
      >>> # with 7 frames per video.
      >>> input_shape = (4, 7, 28, 28, 28, 1)
      >>> x = tf.random.normal(input_shape)
      >>> y = tf.keras.layers.Conv3D(
      ... 2, 3, activation='relu', input_shape=input_shape[2:])(x)
      >>> print(y.shape)
      (4, 7, 26, 26, 26, 2)
      Arguments:
        filters: Integer, the dimensionality of the output space (i.e. the number of
          output filters in the convolution).
        kernel_size: An integer or tuple/list of 3 integers, specifying the depth,
          height and width of the 3D convolution window. Can be a single integer to
          specify the same value for all spatial dimensions.
        strides: An integer or tuple/list of 3 integers, specifying the strides of
          the convolution along each spatial dimension. Can be a single integer to
          specify the same value for all spatial dimensions. Specifying any stride
          value != 1 is incompatible with specifying any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
          `"valid"` means no padding. `"same"` results in padding evenly to
          the left/right or up/down of the input such that output has the same
          height/width dimension as the input.
        data_format: A string, one of `channels_last` (default) or `channels_first`.
          The ordering of the dimensions in the inputs. `channels_last` corresponds
          to inputs with shape `batch_shape + (spatial_dim1, spatial_dim2,
          spatial_dim3, channels)` while `channels_first` corresponds to inputs with
          shape `batch_shape + (channels, spatial_dim1, spatial_dim2,
          spatial_dim3)`. It defaults to the `image_data_format` value found in your
          Keras config file at `~/.keras/keras.json`. If you never set it, then it
          will be "channels_last".
        dilation_rate: an integer or tuple/list of 3 integers, specifying the
          dilation rate to use for dilated convolution. Can be a single integer to
          specify the same value for all spatial dimensions. Currently, specifying
          any `dilation_rate` value != 1 is incompatible with specifying any stride
          value != 1.
        groups: A positive integer specifying the number of groups in which the
          input is split along the channel axis. Each group is convolved separately
          with `filters / groups` filters. The output is the concatenation of all
          the `groups` results along the channel axis. Input channels and `filters`
          must both be divisible by `groups`.
        activation: Activation function to use. If you don't specify anything, no
          activation is applied (see `keras.activations`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix (see
          `keras.initializers`).
        bias_initializer: Initializer for the bias vector (see
          `keras.initializers`).
        kernel_regularizer: Regularizer function applied to the `kernel` weights
          matrix (see `keras.regularizers`).
        bias_regularizer: Regularizer function applied to the bias vector (see
          `keras.regularizers`).
        activity_regularizer: Regularizer function applied to the output of the
          layer (its "activation") (see `keras.regularizers`).
        kernel_constraint: Constraint function applied to the kernel matrix (see
          `keras.constraints`).
        bias_constraint: Constraint function applied to the bias vector (see
          `keras.constraints`).
      Input shape:
        5+D tensor with shape: `batch_shape + (channels, conv_dim1, conv_dim2,
          conv_dim3)` if data_format='channels_first'
        or 5+D tensor with shape: `batch_shape + (conv_dim1, conv_dim2, conv_dim3,
          channels)` if data_format='channels_last'.
      Output shape:
        5+D tensor with shape: `batch_shape + (filters, new_conv_dim1,
          new_conv_dim2, new_conv_dim3)` if data_format='channels_first'
        or 5+D tensor with shape: `batch_shape + (new_conv_dim1, new_conv_dim2,
          new_conv_dim3, filters)` if data_format='channels_last'. `new_conv_dim1`,
          `new_conv_dim2` and `new_conv_dim3` values might have changed due to
          padding.
      Returns:
        A tensor of rank 5+ representing
        `activation(conv3d(inputs, kernel) + bias)`.
      Raises:
        ValueError: if `padding` is "causal".
        ValueError: when both `strides > 1` and `dilation_rate > 1`.
      """

    def __init__(self,
                 filters, kernel_size, dtype=DEFAULT_COMPLEX_TYPE, strides=(1, 1, 1), padding='valid', data_format=None,
                 dilation_rate=(1, 1, 1), groups=1, activation=None, use_bias=True,
                 kernel_initializer=ComplexGlorotUniform(), bias_initializer=Zeros(),
                 kernel_regularizer=None, bias_regularizer=None, activity_regularizer=None,
                 kernel_constraint=None, bias_constraint=None, **kwargs):
        super(ComplexConv3D, self).__init__(
            rank=3, dtype=dtype,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            groups=groups,
            activation=activations.get(activation),
            use_bias=use_bias,
            kernel_initializer=initializers.get(kernel_initializer),
            bias_initializer=initializers.get(bias_initializer),
            kernel_regularizer=regularizers.get(kernel_regularizer),
            bias_regularizer=regularizers.get(bias_regularizer),
            activity_regularizer=regularizers.get(activity_regularizer),
            kernel_constraint=constraints.get(kernel_constraint),
            bias_constraint=constraints.get(bias_constraint),
            **kwargs)