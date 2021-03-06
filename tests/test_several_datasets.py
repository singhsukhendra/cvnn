import tensorflow as tf
import numpy as np
import tensorflow_datasets as tfds
from tensorflow.keras import datasets, models
from cvnn.initializers import ComplexGlorotUniform
from cvnn.layers import ComplexDense, ComplexFlatten, ComplexInput
import cvnn.layers as complex_layers
from cvnn import layers
from pdb import set_trace
from cvnn.montecarlo import run_gaussian_dataset_montecarlo


def normalize_img(image, label):
    """Normalizes images: `uint8` -> `float32`."""
    return tf.cast(image, tf.float32) / 255., label


def mnist_example():
    (ds_train, ds_test), ds_info = tfds.load(
        'mnist',
        split=['train', 'test'],
        shuffle_files=True,
        as_supervised=True,
        with_info=True,
    )
    ds_train = ds_train.map(
        normalize_img, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    ds_train = ds_train.cache()
    ds_train = ds_train.shuffle(ds_info.splits['train'].num_examples)
    ds_train = ds_train.batch(128)
    ds_train = ds_train.prefetch(tf.data.experimental.AUTOTUNE)
    ds_test = ds_test.map(
        normalize_img, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    ds_test = ds_test.batch(128)
    ds_test = ds_test.cache()
    ds_test = ds_test.prefetch(tf.data.experimental.AUTOTUNE)

    model = tf.keras.models.Sequential([
        ComplexFlatten(input_shape=(28, 28, 1)),
        ComplexDense(128, activation='relu', dtype=tf.float32),
        ComplexDense(10, dtype=tf.float32)
    ])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(0.001),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy()],
    )

    model.fit(
        ds_train,
        epochs=2,
        validation_data=ds_test,
    )


def fashion_mnist_example():
    dtype_1 = np.complex64
    fashion_mnist = tf.keras.datasets.fashion_mnist
    (train_images, train_labels), (test_images, test_labels) = fashion_mnist.load_data()
    train_images = train_images.astype(dtype_1)
    test_images = test_images.astype(dtype_1)
    train_labels = train_labels.astype(dtype_1)
    test_labels = test_labels.astype(dtype_1)

    model = tf.keras.Sequential([
        ComplexInput(input_shape=(28, 28)),
        ComplexFlatten(),
        ComplexDense(128, activation='cart_relu', kernel_initializer=ComplexGlorotUniform(seed=0)),
        ComplexDense(10, activation='convert_to_real_with_abs', kernel_initializer=ComplexGlorotUniform(seed=0))
    ])
    model.summary()
    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=['accuracy']
                  )
    model.fit(train_images, train_labels, epochs=2)
    # import pdb; pdb.set_trace()


def cifar10_test():
    dtype_1 = 'complex64'
    (train_images, train_labels), (test_images, test_labels) = datasets.cifar10.load_data()
    # Normalize pixel values to be between 0 and 1
    train_images, test_images = train_images / 255.0, test_images / 255.0
    train_images = train_images.astype(dtype_1)
    test_images = test_images.astype(dtype_1)
    train_labels = train_labels.astype(dtype_1)
    test_labels = test_labels.astype(dtype_1)

    tf.random.set_seed(1)
    hist1 = cifar10_test_model_1(train_images, train_labels, test_images, test_labels, dtype_1)

    tf.random.set_seed(1)
    hist2 = cifar10_test_model_2(train_images, train_labels, test_images, test_labels, dtype_1)

    assert hist1.history == hist2.history


def cifar10_test_model_1(train_images, train_labels, test_images, test_labels, dtype_1='complex64'):
    model = models.Sequential()
    model.add(layers.ComplexInput(input_shape=(32, 32, 3), dtype=dtype_1))  # Never forget this!!!
    model.add(layers.ComplexConv2D(32, (3, 3), activation='cart_relu'))
    model.add(layers.ComplexMaxPooling2D((2, 2)))
    model.add(layers.ComplexConv2D(64, (3, 3), activation='cart_relu'))
    model.add(layers.ComplexAvgPooling2D((2, 2)))
    model.add(layers.ComplexConv2D(64, (3, 3), activation='cart_relu'))
    model.add(layers.ComplexFlatten())
    model.add(layers.ComplexDense(64, activation='cart_relu'))
    model.add(layers.ComplexDense(10, activation='convert_to_real_with_abs'))
    model.summary()
    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=['accuracy'])
    return model.fit(train_images, train_labels, epochs=2, validation_data=(test_images, test_labels), shuffle=False)


def cifar10_test_model_2(train_images, train_labels, test_images, test_labels, dtype_1='complex64'):
    x = layers.complex_input(shape=(32, 32, 3), dtype=dtype_1)
    conv1 = layers.ComplexConv2D(32, (3, 3), activation='cart_relu')(x)
    pool1 = layers.ComplexMaxPooling2D((2, 2))(conv1)
    conv2 = layers.ComplexConv2D(64, (3, 3), activation='cart_relu')(pool1)
    pool2 = layers.ComplexAvgPooling2D((2, 2))(conv2)
    conv3 = layers.ComplexConv2D(64, (3, 3), activation='cart_relu')(pool2)
    flat = layers.ComplexFlatten()(conv3)
    dense1 = layers.ComplexDense(64, activation='cart_relu')(flat)
    y = layers.ComplexDense(10, activation='convert_to_real_with_abs')(dense1)

    model = models.Model(inputs=[x], outputs=[y])
    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=['accuracy'])
    model.summary()
    return model.fit(train_images, train_labels, epochs=2, validation_data=(test_images, test_labels), shuffle=False)


def random_dataset():
    x_train = np.complex64(tf.complex(tf.random.uniform([640, 65, 82, 1]), tf.random.uniform([640, 65, 82, 1])))
    x_test = np.complex64(tf.complex(tf.random.uniform([200, 65, 82, 1]), tf.random.uniform([200, 65, 82, 1])))
    y_train = np.uint8(np.random.randint(5, size=(640, 1)))
    y_test = np.uint8(np.random.randint(5, size=(200, 1)))

    model = tf.keras.models.Sequential()
    model.add(complex_layers.ComplexInput(input_shape=(65, 82, 1)))  # Always use ComplexInput at the start
    model.add(complex_layers.ComplexConv2D(8, (5, 5), activation='cart_relu'))
    model.add(complex_layers.ComplexMaxPooling2D((2, 2)))
    model.add(complex_layers.ComplexConv2D(16, (5, 5), activation='cart_relu'))
    model.add(complex_layers.ComplexFlatten())
    model.add(complex_layers.ComplexDense(256, activation='cart_relu'))
    model.add(complex_layers.ComplexDropout(0.1))
    model.add(complex_layers.ComplexDense(64, activation='cart_relu'))
    model.add(complex_layers.ComplexDropout(0.1))
    model.add(complex_layers.ComplexDense(5, activation='convert_to_real_with_abs'))
    # An activation that casts to real must be used at the last layer.
    # The loss function cannot minimize a complex number

    # Compile it
    model.compile(optimizer='adam',
                  loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=['accuracy'],
                  # run_eagerly=Trutest_regressione
                  )
    model.summary()
    # Train and evaluate
    history = model.fit(x_train, y_train, epochs=2, validation_data=(x_test, y_test))
    test_loss, test_acc = model.evaluate(x_test, y_test, verbose=2)


def test_datasets():
    run_gaussian_dataset_montecarlo(epochs=2, iterations=1)
    random_dataset()
    cifar10_test()
    fashion_mnist_example()
    mnist_example()


if __name__ == '__main__':
    test_datasets()
