# Pose examples

Put one pose image in each file in this directory. PNG, JPG, JPEG and WebP are
supported. The UI preserves each image's natural proportions, including the
portrait images used by the idle carousel and shooting side rails.

Files are discovered automatically and may use names such as `001.png`,
`002.png`, `003.png`. On idle entry the files are shuffled and split evenly
between the three large, slow carousel rows. For every new shooting session the
full pool is shuffled independently. Each camera frame consumes the next
`2 × pose_examples_per_side` unused files: first the left column from top to
bottom, then the right column from top to bottom.

The number shown on each side is configured by `pose_examples_per_side` in
`config_app.json`.
