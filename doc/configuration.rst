Configuration Options
---------------------

In the table below, ``<h> = ~\PCMCam``, where ``~`` is the users's home directory, so e.g. ``C:\Users\joeavg``,
for a user named ``joeavg``.

Configuration options in the ``[DEFAULT]`` section:

+-----------------+-------------+---------------------------------------------------------------+
| Parameters      | Default     | Description                                                   |
+=================+=============+===============================================================+
| CaptureDir      | <h>\\caps   | place to store auto-captured images                           |
+-----------------+-------------+---------------------------------------------------------------+
| FlatFieldCalDir | <h>\\FFC    | path to flat-field calibration files                          |
+-----------------+-------------+---------------------------------------------------------------+
| ImageDir        | <h>\\images | (not implemented)                                             |
+-----------------+-------------+---------------------------------------------------------------+

Configuration options in the ``[Options]`` section:

+-----------------+-------------+-------------------------------------------------------------------+
| Parameters      | Default     | Description                                                       |
+=================+=============+===================================================================+
| CaptureAutoSave | True        | When true, captures  also saved to ``CaptureDir``                 |
+-----------------+-------------+-------------------------------------------------------------------+
| SoundOnCapture  | True        | set to cause a shutter sound to be played on capture              |
+-----------------+-------------+-------------------------------------------------------------------+
| ExpInit1        | 50          | initial exposure setting in ms, group 1.                          |
+-----------------+-------------+-------------------------------------------------------------------+
| ExpInit2        | 1000        | initial exposure setting in ms, group 2.                          |
+-----------------+-------------+-------------------------------------------------------------------+
| CalAutoLoad     | True        | set to cause FFC files to be automatically loaded on program start|
+-----------------+-------------+-------------------------------------------------------------------+
| CalAutoSave     | True        | set to cause FFC files to be automatically saved when reacquired  |
+-----------------+-------------+-------------------------------------------------------------------+
| BlackCorrect    | True        | enable on-the-fly black flat-field correction                     |
+-----------------+-------------+-------------------------------------------------------------------+
| TiffSeqXWindow  | 1024        | Horizontal window size for Tiff Stack captures                    |
+-----------------+-------------+-------------------------------------------------------------------+
| TiffSeqYWindow  | 1024        | Vertical window size for Tiff Stack captures                      |
+-----------------+-------------+-------------------------------------------------------------------+
| TiffSeqRebin    | 2           | Rebinning factor for Tiff Stack captures 2 = 2x2, 4 = 4x4         |
+-----------------+-------------+-------------------------------------------------------------------+

