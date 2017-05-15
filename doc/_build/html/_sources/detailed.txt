Detailed Operation
------------------

Main Display
^^^^^^^^^^^^
|main_screen_corner|

The main screen (unless swapped) shows a live stream form the camera.  At the top left, the camera exposure time and
frame rate are displayed.  At the top right, the mouse cursor position (x, y) is displayed.

Keyboard
........

The program will respond to certain keyboard entries as follows:

+------------+--------------------------------------------------+
| Key        | Function                                         |
+============+==================================================+
| ``A``      | Delete All arrows and ROIs.                      |
+------------+--------------------------------------------------+
| ``C``      | Capture frame and store to the capture palette.  |
+------------+--------------------------------------------------+
| ``S``      | Swap role of live and captured screens.          |
+------------+--------------------------------------------------+
| ``T``      | Toggle exposure groups.                          |
+------------+--------------------------------------------------+
| ``Delete`` | Delete activated ROI or arrow.                   |
+------------+--------------------------------------------------+

ROIs
....
|roi|

An *ROI* is a region of interest - a closed polygon.  It can be used purely as graphical object to mark up the
display but it also has a function in setting the display contrast/brightness. To draw an ROI, start with a
double-click at the first vertex, single clicks of the left mouse button for each subsequent vertex,
and then a double click to define the final vertex and close the polygon.

The ROI can be activated by hovering over the ROI so that it changes color then single-click the left mouse button.
The vertices will reappear.  Once activated the ROI can be moved by dragging from somewhere inside the ROI
polygon, or any one of the vertices can be moved by dragging from inside that point.

To delete the ROI, activate it and press the delete key.

Arrows
......
|arrow|

An arrow is purely graphical.  It has no function.  Draw it by aiming the mouse cursor at the live screen where
you want the arrow head to appear and then dragging to form the tail.  When you release the mouse button, the arrowhead
will appear.  To activate an arrow, you must click on th arrow head.  Arrows can't be moved.  Delete an arrow by
activating it then pressing the delete key.

Contrast/Brightness
^^^^^^^^^^^^^^^^^^^
|contrast_brightness|

This section of the screen controls the brightness and contrast settings.  There is a live histogram displaying the
distribution of pixel values.  The horizontal axis always shows the full range of possible pixel values (256 for 8-bit
cameras, 1024 for 10-bit cameras, 4096 for 12-bit).  There are slider controls above and below the histogram to control
the brightness/contrast window.

Keep in mind that the contrast/brightness controls affect the display
parameters - they do not control camera settings.  If the display is very dim, it may be better to increase
the exposure time for a better signal to noise ratio.

+---------------+-------------------------------------------------------------------+
| Control       | Function                                                          |
+===============+===================================================================+
| upper slider  | Sets the pixel value corresponding to fully-saturated white       |
+---------------+-------------------------------------------------------------------+
| lower slider  | Sets the pixel value corresponding to black                       |
+---------------+-------------------------------------------------------------------+
| |b_reset|     | Resets contrast/brightness to 0=black, 100%=white                 |
+---------------+-------------------------------------------------------------------+
| |b_global|    | Sets contrast/brightness to include full range of pixels.  I.e.   |
|               | black is set to the minimum pixel value, white to the max.        |
+---------------+-------------------------------------------------------------------+
| |b_roi|       | Sets contrast/brightness to the range of pixels contained within  |
|               | the ROI                                                           |
+---------------+-------------------------------------------------------------------+

Exposure Controls
^^^^^^^^^^^^^^^^^
|exposure_controls|

+---------------+-------------------------------------------------------------------+
| Control       | Function                                                          |
+===============+===================================================================+
| |g_bright|    | select exposure group 1 - Bright/NIR - and exposure time (ms)     |
+---------------+-------------------------------------------------------------------+
| |g_fluor|     | select exposure group 2 - Fluorescence - and exposure time (ms)   |
+---------------+-------------------------------------------------------------------+
| |b_cal|       | start flat-field calibration                                      |
+---------------+-------------------------------------------------------------------+

One of the two exposure groups is active at a time.  Selecting one deactivates the other. Each exposure group is
associated with an exposure duration that's selected from a drop-down list of possible exposure settings.  The
exposure group is also associated with the contrast/brightness settings so when toggling between groups, the
contrast/brightness will also be retained.

Flat-field calibration is performed while no illumination is present.  The software will cycle through all the
selectable exposure settings and record a black image.  This dark-field correction will be subtracted from
all subsequent live streams.  The dark-field images are also stored (if enabled) to a folder and loaded (if
enabled) when the program starts up.

Relationship Between Exposure Time and Frame Rate
.................................................
The camera frame rate cannot be higher than the inverse of the exposure time.  So, for example, if the exposure time
is 400 ms, the frame rate will be at most 2.5 FPS.  There is also a limit imposed by the software of (currently) 5
frames per second so reducing the exposure time below 200 ms doesn't increase the frame rate.


Capture Palette
^^^^^^^^^^^^^^^
|capture_palette|

+---------------+-------------------------------------------------------------------+
| Control       | Function                                                          |
+===============+===================================================================+
| slider        | page through stack of captured frames                             |
+---------------+-------------------------------------------------------------------+
| |b_capture|   | capture the current frame                                         |
+---------------+-------------------------------------------------------------------+
| |b_swap|      | swap the roles of the main and capture palette screens            |
+---------------+-------------------------------------------------------------------+

The capture palette keeps track of captured frames.  Add a new frame by pressing the |b_capture| button or ``C`` on
the keyboard.  You can scroll through the stack (deck) of captured frames using the slider control.

Captured frames are also saved (if enabled) to image files in a folder.  The format of stored captured frames is
16-bit gray-scale TIFF.  Files are stored in the capture directory in a folder named for the date and a filename
consisting of the program invocation time and the capture number.  That capture number corresponds to the capture
number showing on the heading of the capture palette.

.. |exposure_controls| image:: graphics/exposure_controls.png
.. |contrast_brightness| image:: graphics/contrast_brightness.png
.. |b_reset| image:: graphics/b_reset.png
.. |b_global| image:: graphics/b_global.png
.. |b_roi| image:: graphics/b_roi.png
.. |capture_palette| image:: graphics/capture_palette.png
.. |main_screen_corner| image:: graphics/main_screen_corner.png
.. |arrow| image:: graphics/arrow.png
.. |roi| image:: graphics/roi.png
.. |g_bright| image:: graphics/g_bright.png
.. |g_fluor| image:: graphics/g_fluor.png
.. |b_cal| image:: graphics/b_cal.png
.. |b_capture| image:: graphics/b_capture.png
.. |b_swap| image:: graphics/b_swap.png

