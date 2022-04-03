Installation Steps
==================
The program is written in Python 3.  The recommended Python distribution (there are many) is Anaconda.  In addition,
PCMCam makes use of two packages that are not included by default in the Anaconda distribution: ``Qt5`` and ``Open CV``.

Installing Python 3
-------------------
Download and setup a Python 3 system from the `Anaconda`_ website.

.. _Anaconda: https://www.continuum.io/downloads

Follow the steps provided by Continuum to install Python 3.6 for Windows, either 64-bit or 32-bit depending on your OS.

Installing Dependent Packages
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Launch the Windows Command utility (DOS or System) and at the prompt, enter the following commands::

    conda update --all
    conda install --channel https://conda.anaconda.org/menpo opencv3
    conda install --channel https://conda.anaconda.org/m-labs pyqt5

You may need to answer various prompts during each of these steps.

Installing Camera Drivers
-------------------------
The appropriate driver must be installed.

Thorlabs DCx (IDS XXX)
^^^^^^^^^^^^^^^^^^^^^^
Do not install the driver from Thorlabs - it's out of date and not compatible with Python 3.6.  If the Thorlabs
software has already been installed, uninstall it using *Programs and Features* in the Windows
*control panel*.

Download the ueye driver from `IDS`_.  You need to register with IDS to get to the actual download page.  Choose the
version (32-bit or 64-bit, Windows) that is appropriate for your system.

.. _IDS: https://en.ids-imaging.com/download-ueye-win64.html

Versions Information
--------------------
The following versions are known to work correctly

+------------+--------+
|Anaconda    | 4.1.0  |
+------------+--------+
|Python      | 3.6.3  |
+------------+--------+
|ueye driver | 4.80.5 |
+------------+--------+
