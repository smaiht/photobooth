# Pose examples

Put one pose image in each file in this directory. Square images are the
recommended format, but rectangular PNG, JPG, JPEG and WebP files are also
safe: the UI preserves their proportions and centers them in the side rail.

Files are discovered automatically and sorted naturally by filename, so use
names such as `001.png`, `002.png`, `003.png`. For every camera frame the UI
takes the next `2 × pose_examples_per_side` files: first the left column from
top to bottom, then the right column from top to bottom. After the final file,
the sequence starts again from the beginning.

The number shown on each side is configured by `pose_examples_per_side` in
`config_app.json`.
