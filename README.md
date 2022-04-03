# PCMCam
PCMCam - Patch Clamp Microscopy Camera
======================================

Introduction
------------

PCMCam is a program for controlling a microscope camera that was designed specifically for patch-clamp applications.
Features include:

* Dark-field correction for CCD cameras
* Single keystroke capture to internal palette and disk ("C" key)
* Rapid swapping of live screen and stills ("S" key)
* Two independent exposure settings intended to be associated with bright-field/NIR and fluorescence respectively.

Python Installation
-------------------

A Python 3.7+ is required:
* download and install (admin) Anaconda python
* install two additional packages (as admin):
    * conda install -c conda-forge opencv
    * pip install pyueye

conda search pyqt
conda install pyqt=5.9.2=py37ha878b3d_0

