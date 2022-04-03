"""
PCMicro - Patch Clamp Microscope Camera Software.

Command line script.  Works with Python 3.5, Qt5. 
Originally created April 2016 by Matthew Palmer.

Some updates.
3/20/2019 - Dependence on iDS pyueue python API.
            Works with Pyhon 3.7.

"""
import sys
import os
import configparser
import time
import ctypes
import argparse
import PIL.Image
import PIL.TiffImagePlugin as PTIP
#from PIL.TiffImagePlugin import AppendingTiffWriter
import doriclib


from PyQt5 import QtMultimedia
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt

import cv2

from mplcanvas import MplCanvas
from datetime import datetime

import numpy as np
from matplotlib.path import Path
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from ctypes import wintypes
import cameras
from screens import CapScreen, LiveScreen, TimeLapseScreen


"""
Global parameters:
"""

#TIFF_COMPRESSION = 'tiff_lzw'   # IF you compress, you lose (non-core) tags.
TIFF_COMPRESSION = 'raw'


# Video format.  Must be a FourCC codec supported by OpenCV (FFMPEG)
#VIDEO_FORMAT = 'FFV1'   # lossless
VIDEO_FORMAT = 'DIVX'  # lossy

GAIN_TRACE_COLOR = 'r' # Matplotlib color
HIST_TRACE_COLOR = 'b'
HIST_NBINS = 64

FPS_AVERAGES = 5

FRAME_WIDTH = cameras.FRAME_WIDTH
FRAME_HEIGHT = cameras.FRAME_HEIGHT
FRAME_SHAPE = (FRAME_HEIGHT, FRAME_WIDTH)

__AUTHOR__ = 'Palmer'
__PROGRAM_NAME__ = 'PCMCam'
__VERSION__ = '1.42'

BANNER = __PROGRAM_NAME__ + ' ' + __VERSION__
PROG_APP_ID = __AUTHOR__ + '.' + __PROGRAM_NAME__ + '.' + __VERSION__

PACKAGE_DIR = os.path.split(os.path.realpath(__file__))[0]
USER_HOME_DIR = os.path.expanduser("~")
USER_PROG_HOME_DIR = os.path.join(USER_HOME_DIR, __PROGRAM_NAME__)

MEDIA_DIR = os.path.join(PACKAGE_DIR, 'media')

PROG_ICON_FILE = os.path.join(MEDIA_DIR, 'patch_icon.ico')
CAMERA_CLICK_FILE = os.path.join(MEDIA_DIR, 'camera.wav')

CONFIG_FILENAME = os.path.join(USER_PROG_HOME_DIR, __PROGRAM_NAME__) + '.ini'
CONFIG_TEMPLATE = os.path.join(PACKAGE_DIR, __PROGRAM_NAME__) + '.000'
BAT_FILENAME = os.path.join(USER_PROG_HOME_DIR, __PROGRAM_NAME__) + '.bat'




class FlatFieldCal(object):
    """
    Class for managing flat-field calibration.

    Currently calibration is only dark-field.  This seems to be the most important.  In memory, this is stored in
    array ``black``.  In addition, this class manages file-based copies, arrays stored in numpy format.  if a directory
    name is passed to init, or when the load method is called, the full ``black`` array is loaded from that path.
    During a new calibration sequence, the array for that exposure is writen to the file when it's been acquired.
    """
    def __init__(self, parent):
        """

        Parameters
        ----------
        parent : QObject
            parent window (I think)
        """
        self.acq_state = 0 # 0=normal, 1=acquiring black correction
        self.frame = 0 # frame counter
        self.exp_ind = 0  # exposure index counter (for cycling)
        self.hold_exp_indices = [0, 0] # copy of currently set exposure index
        self.parent = parent
        self.camera = parent.camera
        self.config = parent.config
        self.progdialog = None          # to be set

        if self.config.cal_auto_load:
            self.load()
        else:
            self.black = []
            for e in self.camera.exposure_settings:
                self.black.append(np.zeros(FRAME_SHAPE, np.int16))
        self.prior_black = None

    def load(self):
        """
        Load calibration files into memory.

        Returns
        -------

        """
        self.black = []

        for e in self.camera.exposure_settings:
            p = os.path.join(self.config.ffc_dir, 'BLK%5.5d.npy' % e)
            if os.path.isfile(p):
                print('Loading cal: ', p)
                self.black.append(np.load(p).astype(np.int16))  # older versions might have saved uint
            else:
                self.black.append(np.zeros(FRAME_SHAPE, np.int16))

    def start_black_cal(self):
        self.hold_exp_indices = [self.camera.current_exposure_index, self.camera.current_ifi_index] # for later restoration
        self.frame_ind = 0 # frame counter
        self.exp_ind = 0 # exposure index counter (for cycling)
        self.prior_black = np.copy(self.black[0])
        self.black[0].fill(0) # because black integrates frames during cal sequence.
        self.discard_next = True
        self.camera.set_cal_state(True) # notify the camera api in case it needs to know we are calibrating
        self.camera.set_exposure(self.exp_ind, 0)
        self.acq_state = 1 # internal indicator that we are calibrating

        self.progdialog = QtWidgets.QProgressDialog(
            "Black Field Calibration", "Cancel", 0, len(self.camera.exposure_settings), self.parent)
        self.progdialog.setWindowTitle("Calibration")
        self.progdialog.canceled.connect(self.cancel_cal)
        self.progdialog.setModal(True)
        self.progdialog.setAutoClose(True)
        self.progdialog.setAttribute(Qt.WA_DeleteOnClose, True)
        """
        Turn off "?" in window title, see http://stackoverflow.com/questions/81627/how-can-i-hide-delete-the-help-button-on-the-title-bar-of-a-qt-dialog
        """
        self.progdialog.setWindowFlags(self.progdialog.windowFlags() & ~Qt.WindowContextHelpButtonHint )

        self.progdialog.exec_() #remember exec_ blocks execution until cal is done.

        #self.update_progress()

    def cancel_cal(self):
        self.stop_cal()
        self.progdialog.close()

    def update_progress(self):
        self.progdialog.setValue(self.exp_ind)
        if self.exp_ind < len(self.camera.exposure_settings):
            self.progdialog.setLabelText('Calibrating %d ms exposure...' % self.camera.exposure_settings[self.exp_ind])


    def next_cal(self):
        self.black[self.exp_ind] //= self.camera.black_cal_averages[self.exp_ind]


        std = np.std(self.prior_black - self.black[self.exp_ind])

        print('Exposure: %d ms, black mean %.1f, RMS error from previous: %.1f' %
              (self.camera.exposure_settings[self.exp_ind], self.black[self.exp_ind].mean(), std))

        if self.config.cal_auto_save:
            if not os.path.isdir(self.config.ffc_dir):
                os.makedirs(self.config.ffc_dir)
            p = os.path.join(self.config.ffc_dir, 'BLK%5.5d.npy' % self.camera.exposure_settings[self.exp_ind])
            print('writing: ', p)
            np.save(p, self.black[self.exp_ind])

        #return self.stop_cal()
        
        self.exp_ind += 1
        if self.exp_ind == len(self.camera.exposure_settings):
            self.stop_cal()
        else:
            self.frame_ind = 0
            self.prior_black = np.copy(self.black[self.exp_ind])
            self.black[self.exp_ind].fill(0) # because black integrates frames during cal sequence.
            self.camera.set_exposure(self.exp_ind, 0)

        self.update_progress()

    def stop_cal(self):
        self.camera.set_exposure(self.hold_exp_indices[0], self.hold_exp_indices[1])
        self.camera.set_cal_state(False)
        self.acq_state = 0
        self.progdialog.setValue(len(self.camera.exposure_settings))

    def accumulate_frame(self, frame):
        self.black[self.exp_ind] += frame
        self.frame_ind += 1
        if self.frame_ind == self.camera.black_cal_averages[self.exp_ind]:
            self.next_cal()

    def black_correct(self, frame):
        if self.calibrating:
            if self.discard_next:
                self.discard_next = False
                return frame
            self.accumulate_frame(frame)
            return frame
        else:
            return np.maximum(0, frame - self.black[self.camera.current_exposure_index])

    @property
    def calibrating(self):
        return self.acq_state != 0



class DispParam(object):
    """
    Structure for setting up and managing display parameters and buffers
    """
    def __init__(self):
        self.iwindow = [[0., 100.]]  # intensity range as percent
        self.latest_frame = None           # Most recent frame
        self.frame_timestamp = [datetime.now()]
        self.n_caps = 0
        self.cur_cap = None          # current capture that's displayed
        self.caps_saved = True
        self.cap_live_swap = False   # true when live and capture screens are swapped
        self.fps_history = []
        self.fps_estimate = 0.
        self.iwindow_toggle_save = [0., 100.] # place to store windows values across exp-toggling

    def clear_caps(self):
        """
        Clear the capture buffers.
        """

        self.iwindow = self.iwindow[:1]
        self.frame_timestamp = self.frame_timestamp[:1]
        self.n_caps = 0
        self.cur_cap = None
        self.caps_saved = True

    def update_fps(self, fps):
        """
        fps is computed from a moving average.

        Parameters
        ----------
        fps : (float)
            latest fps value to add to the brief history
        Returns
        -------
        avgfps : (float)
            updated smoothed fps
        """
        self.fps_history.append(fps)
        if len(self.fps_history) > FPS_AVERAGES:
            self.fps_history.pop(0)

        self.fps_estimate = np.mean(self.fps_history)
        return self.fps_estimate


class HistCanvas(MplCanvas):
    """Histogram Figure Canvas and QWidget"""

    """
    def __init__(self,  *args):
        super().__init__(*args)

        position = [0., 0., 1., 1.]

        self.axes.hold(True)        
        self.axes.set_position(position)
        self.axes.yaxis.set_visible(False)
        self.axes.xaxis.set_visible(False)
        self.axes.set_frame_on(False)
    """
    def compute_initial_figure(self):
        
        gcx_shrink = 0.8
        gcx_offset = (1. - gcx_shrink)/2.

        position = [gcx_offset, 0., gcx_shrink, 1.]
        self.axes.set_position(position)
        self.axes.yaxis.set_visible(False)
        self.axes.xaxis.set_visible(False)
        self.axes.set_frame_on(True)

        l = Line2D([], [], color=GAIN_TRACE_COLOR)
        self.gain_trace = self.axes.add_line(l)

        """
        l = Line2D([], [], color=HIST_TRACE_COLOR)
        self.hist_trace = self.axes.add_line(l)
        """

        hcurve_y = np.arange(HIST_NBINS) / HIST_NBINS
        hcurve_x = np.arange(HIST_NBINS) / HIST_NBINS
        self.hist_bars = self.axes.bar(hcurve_x, hcurve_y, color = HIST_TRACE_COLOR, width=1./HIST_NBINS)

        #self.gain_graph = self.axes.plot([0, 1.], [0, 1.], color = HIST_TRACE_COLOR)

class TimeStamp():
    def __init__(self, label_widget):
        self.lw = label_widget
        self.reset()

    def reset(self):
        self.ts = datetime.now()
        self.lw.setText(self.time_string())

    def date_string(self):
        return self.ts.strftime('%Y-%m-%d')

    def time_string(self):
        return self.ts.strftime('%H%M%S')

def now_with_f_secs():
    """
    Helper function
    Parameters
    ----------
    self

    Returns
    -------

    """
    now = datetime.now()
    ms = int(now.microsecond /10000.)
    return '%s.%2.2d\t' % (now.strftime('%H:%M:%S'), ms)



class Viewer(QtWidgets.QMainWindow):
    def __init__(self, config, cam_index):
        def _closest(the_list, the_val):
            v = min(the_list, key=lambda x: abs(x - the_val))
            return the_list.index(v)

        super().__init__()

        self.config = config

        self.dpar = DispParam()

        self.setup_graphics_view()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle(BANNER)
        self.timestamp = TimeStamp(self.epoch_label)


        """
        see http://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105
        """
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(PROG_APP_ID)
        self.setWindowIcon(QtGui.QIcon(PROG_ICON_FILE))

        if int(cam_index) == 0:
            # lookup and build menu listof UC480 camera(s)

            Pref = 'UC480: '
            self.uc480_camera = cameras.UC480_Camera()

            if self.uc480_camera.dev_list is None:
                raise SystemExit('%s: --no library--' % Pref)
            elif len(self.uc480_camera.dev_list) == 0:
                raise SystemExit('%s: --no devices--' % Pref)
            sttstr = Pref + '%d/%s/%s' % self.uc480_camera.dev_list[0]
            self.camera = self.uc480_camera

        elif int(cam_index) == 1:
            # lookup and build menu listof Webcam camera(s)
            Pref = 'WebCam: '
            self.web_camera = cameras.Web_Camera()
            if self.web_camera.dev_list is None:
                raise SystemExit('%s: --no library--' % Pref)
            elif len(self.web_camera.dev_list) == 0:
                raise SystemExit('%s: --no devices--' % Pref)
            sttstr = Pref + '%d/%s/%s' % self.web_camera.dev_list[0]
            self.camera = self.web_camera

        elif int(cam_index) == 2:
            # lookup and build menu listof Pseudo camera(s)
            Pref = 'Pseudo: '
            self.pseudo_camera = cameras.Pseudo_Camera()
    
            sttstr = Pref + '%d/%s/%s' % self.pseudo_camera.dev_list[0]
            self.camera = self.pseudo_camera
        
        else:
            raise SystemExit('Unknown Camera type: <%s>' % cam_index)

        self.cam_label.setText(sttstr)
        self.camera.connect(self.winId())
        if self.config.black_correct:
            self.ffc = FlatFieldCal(self)
        self.dpar.iwindow = [[0., 100.]]

        self.recording_sequence = False
        self.recording_video = False
        self.recorded_video_frame_number = 0
        self.video_number = 0
        self.seq_number = 0

        self.exp1_select.addItems([str(e) for e in self.camera.exposure_settings])
        self.exp1_ifi_select.addItems([str(e/1000.) for e in self.camera.ifi_settings])
        ndx = _closest(self.camera.exposure_settings, self.config.exp_init1)
        self.exp1_select.setCurrentIndex(ndx)
        self.exp1_select.currentIndexChanged.connect(self.__exp1_changed_callback)
        self.exp1_ifi_select.currentIndexChanged.connect(self.__exp1_ifi_changed_callback)

        self.camera.set_exposure(ndx, 0)

        self.exp2_select.addItems([str(e) for e in self.camera.exposure_settings])
        self.exp2_ifi_select.addItems([str(e/1000.) for e in self.camera.ifi_settings])
        ndx = _closest(self.camera.exposure_settings, self.config.exp_init2)
        self.exp2_select.setCurrentIndex(ndx)
        self.exp2_select.currentIndexChanged.connect(self.__exp2_changed_callback)
        self.exp2_ifi_select.currentIndexChanged.connect(self.__exp2_ifi_changed_callback)

        self.exp1_radio.setChecked(True)
        self.exp1_radio.toggled.connect(self.select_exposure)

        self.led_auto_radio.setChecked(True)        # this also triggers the

        self.camera.start_sampling(self.update_frame)
        
        
    def keyPressEvent(self, event):
        """
        Intercept keystrokes.  Note that buttons used by QGUI are problematic (e.g. space bar)
        Current keystroke actions:
            S - swap live and capture screens
            C - capture
            T - toggle exposure group
            <del> - delete the active arrow or ROI
        """
        if type(event) == QtGui.QKeyEvent:
            if event.key() == Qt.Key_S:
                if self.swap_button.isEnabled():
                    self.swap_cap_live()

            if event.key() == Qt.Key_C:
                self.capture()

            if event.key() == Qt.Key_R:
                if self.rec_seq_button.isEnabled():
                    self.record_sequence()

            if event.key() == Qt.Key_T:
                self.toggle_exposure()

            if event.key() == Qt.Key_Delete:
                """
                Look for activated ROI and delete it.
                """
                self.live_screen.delete_activated()

            if event.key() == Qt.Key_A:
                self.live_screen.delete_features()
                

    def nativeEvent(self, eventType, message):
        msg = wintypes.MSG.from_address(message.__int__())
        if self.camera is not None:
            if self.camera.uses_messages:
                return self.camera.msg_event(msg)
        
        return False, 0

    def __exp1_ifi_changed_callback(self, ifi_ndx):
        """
        Called when interframe interval selection is changed.  Revise it if the iif is too low, i.e. must
        be greater than current
        """

        self.exp1_radio.setChecked(True)

        if self.recording_sequence:
            self.record_sequence()

        exp_ndx = self.exp1_select.currentIndex()
        if ifi_ndx != 0:
            e = self.camera.exposure_settings[exp_ndx]
            ndx_possible = [n for n, i in enumerate(self.camera.ifi_settings) if i > e]
            if len(ndx_possible) == 0:
                ifi_ndx = 0
                self.exp1_ifi_select.setCurrentIndex(0)
            elif ndx_possible[0] > ifi_ndx:
                ifi_ndx = ndx_possible[0]
                self.exp1_ifi_select.setCurrentIndex(ifi_ndx)

        self.rec_seq_button.setEnabled(ifi_ndx > 0)

        self.camera.set_exposure(exp_ndx, ifi_ndx)

    def __exp2_ifi_changed_callback(self, ifi_ndx):

        self.exp2_radio.setChecked(True)

        if self.recording_sequence:
            self.record_sequence()

        exp_ndx = self.exp2_select.currentIndex()
        if ifi_ndx != 0:
            e = self.camera.exposure_settings[exp_ndx]
            ndx_possible = [n for n, i in enumerate(self.camera.ifi_settings) if i > e]
            if len(ndx_possible) == 0:
                ifi_ndx = 0
                self.exp2_ifi_select.setCurrentIndex(0)
            elif ndx_possible[0] > ifi_ndx:
                ifi_ndx = ndx_possible[0]
                self.exp2_ifi_select.setCurrentIndex(ifi_ndx)

        self.rec_seq_button.setEnabled(ifi_ndx > 0)

        self.camera.set_exposure(exp_ndx, ifi_ndx)


    def __exp1_changed_callback(self, ndx):
        """
        Callback for exposure 1 (bright) drop-down

        Parameters
        ----------
        ndx : index of currently selected item.

        Returns
        -------

        """
        if self.recording_sequence:
            self.record_sequence()
        self.exp1_radio.setChecked(True)
        self.exp1_ifi_select.setCurrentIndex(0)
        self.camera.set_exposure(ndx, 0)
        self.rec_seq_button.setEnabled(False)
        et = np.int(np.round(self.camera.actual_exposure_time_ms))
        self.write_to_log('Exposure %d ms' % et)


    def __exp2_changed_callback(self, ndx):
        """
        Callback for exposure 2 (fluoro) drop-down

        Parameters
        ----------
        ndx : index of currently selected item.

        Returns
        -------

        """
        if self.recording_sequence:
            self.record_sequence()
        self.exp2_radio.setChecked(True)
        self.exp2_ifi_select.setCurrentIndex(0)
        self.camera.set_exposure(ndx, 0)
        self.rec_seq_button.setEnabled(False)
        et = np.int(np.round(self.camera.actual_exposure_time_ms))
        self.write_to_log('Exposure %d ms' % et)



    def toggle_exposure(self):
        """
        Swap currently active (exp1 <--> exp2) exposure.

        Remember, the buttons are mutually exclusive so only need to set the one that's not checked.

        Returns
        -------

        """

        checked1 = self.exp1_radio.isChecked()
        if checked1:
            self.exp2_radio.setChecked(True)
        else:
            self.exp1_radio.setChecked(True)
        self.select_exposure()


    def select_exposure(self):
        """
        Select the currently active (exp1 or exp2) exposure settings

        Callback for exposure radio button for exp1 (bright).  No need for separate callback for exp2 since it's
        the inverse.  The two must get linked by the GUI grouping.
        Parameters
        ----------
        enabled

        Returns
        -------

        """
        exp1_selected = self.exp1_radio.isChecked()

        if self.recording_sequence:
            self.record_sequence() # stop current recording

        if exp1_selected:   # then exp1
            ifi_ndx = self.exp1_ifi_select.currentIndex()
            self.camera.set_exposure(self.exp1_select.currentIndex(), ifi_ndx)
        else:
            ifi_ndx = self.exp2_ifi_select.currentIndex()
            self.camera.set_exposure(self.exp2_select.currentIndex(), ifi_ndx)

        temp = list(self.dpar.iwindow_toggle_save)
        self.dpar.iwindow_toggle_save = list(self.dpar.iwindow[0])
        self.dpar.iwindow[0] = temp
        self._update_scrollbars()

        self.rec_seq_button.setEnabled(ifi_ndx > 0)

        et = np.int(np.round(self.camera.actual_exposure_time_ms))
        self.write_to_log('Exposure %d ms' % et)

    def swap_cap_live(self):
        """
        Swap the roles of the Live screen and capture palette.

        Returns
        -------
        none
        """

        if self.dpar.n_caps == 0:       # probably not needed - this is controlled by button visibility
            return
        self.dpar.cap_live_swap = not self.dpar.cap_live_swap

        if self.dpar.cap_live_swap:
            self.live_screen.format_for_cap()
            self.cap_screen.format_for_live()
        else:
            self.live_screen.format_for_live()
            self.cap_screen.format_for_cap()

        self.update_cap_image()

    def _get_session_dir(self):
        """
        Return the dir path for the current session.  This is the directory that contains captures
        and log file and videos.  If it doesn't exist yet, make it.
        Returns
        -------

        """

        fnd = os.path.join(self.config.capture_dir, self.timestamp.date_string(), self.timestamp.time_string())
        if not os.path.isdir(fnd):
            os.makedirs(fnd)

        return fnd

    def _get_log_filename(self):
        """
        return the path to the current log filename.  Log filename is constructed from the same

        See also _get_cap_filename, makes the director if
        it doesn't exist yet..
        """
        fnd = self._get_session_dir()
        fn = os.path.join(fnd, '%s.log' % self.timestamp.time_string())

        if not os.path.exists(fn):
            with open(fn, 'wt') as log_file:
                log_file.write('Log Created %s by ' % str(datetime.now()))
                log_file.write('%s V%s\n' % (__PROGRAM_NAME__, __VERSION__))

        return fn

    def _get_cap_filename(self):
        """
        return the path to the current capture filename.  Also, make the directory, in case it
        doesn't yet exist.
        """

        fnd = self._get_session_dir()
        fn = os.path.join(fnd,  'F%4.4d.tif' % self.dpar.cur_cap)

        return fn

    def _get_video_filename(self):
        """
        return name of next file to use for recording video.

        Returns
        -------

        """
        fnd = self._get_session_dir()
        self.video_number += 1
        fn = os.path.join(fnd, 'V%4.4d.avi' % self.video_number)
        return fn


    def _get_seq_filename(self):
        """
        return name of next file to use for recording sequences

        Returns
        -------

        """
        fnd = self._get_session_dir()
        self.seq_number += 1
        fn = os.path.join(fnd, 'S%4.4d.tif' % self.seq_number)
        return fn


    def write_to_log(self, line):
        """

        Parameters
        ----------
        line : str
            single line to write to log file and log screen

        Returns
        -------

        """


        now = now_with_f_secs()
        stamped_line = now + '\t' + line

        self.log_screen.appendPlainText(stamped_line.replace('\t', '  '))

        lfn = self._get_log_filename()
        with open(lfn, 'at') as log_file:
            log_file.write(stamped_line)
            log_file.write('\n')




    def capture(self):
        """
        Perform a capture operation.

        The process is as follows:
            * make a copy of the most recent live frame (dpar.latest_frame).
            * append this, the window settings, and a timestamp to the respective lists in self.dpar
            * play a sound (if configured to do so and unless recording is active
            * write this capture to a file (autosave) if configured to do so but now always works
            * update the capture palette (titles, colors...)

        Returns
        -------

        """

        self.dpar.n_caps += 1
        self.dpar.caps_saved = False
        self.cap_screen.cap_loaded = True
        tstamp = datetime.now()

        self.dpar.cur_cap = self.dpar.n_caps
        self.dpar.iwindow.append(list(self.dpar.iwindow[0]))  # deep copy
        self.dpar.frame_timestamp.append(tstamp)

        self.cap_scrollbar.setRange(1, self.dpar.n_caps)
        self.cap_scrollbar.setValue(self.dpar.n_caps)

        if self.config.sound_on_capture:
            QtMultimedia.QSound.play(CAMERA_CLICK_FILE)

        # Always write to file (3/2018)
        """
        Write the capture to a file.  Create the daily capture directory if not yet created.
        """

        #im = Image.fromarray(d, mode='F')  # float32
        #im.save("test2.tiff", "TIFF")
        # https://gist.github.com/ax3l/5781ce80b19d7df3f549#pillow

        """
        Note that despite lack of documenation, this does save as 16-bit gray-scale image.  Open in Photoshop to
        confirm. Irfan converts to 8 bpp upon opening ans scales pixels
        """
        cfn = self._get_cap_filename()
        cap_image = np.copy(self.dpar.latest_frame).astype(np.uint16)
        im = PIL.Image.fromarray((cap_image << (16 - self.camera.pixel_bits)).astype(np.uint16))
        im.save(cfn, 'TIFF')

        """        
        cap_image = np.copy(self.dpar.latest_frame).astype(np.uint16)
        cv2.imwrite(cfn, (cap_image << (16 - self.camera.pixel_bits)).astype(np.uint16))
        """

        et = np.int(np.round(self.camera.actual_exposure_time_ms))
        fn = os.path.basename(cfn)

        self.write_to_log('%d\t%s' % (et, fn))

        self.swap_button.setEnabled(True)
        self.update_cap_image()


    def _get_pixmap(self, frame, iwin):
        
        sframe = frame.astype(np.float)/self.camera.pixel_maxval

        smin, smax = iwin[0]/100., iwin[1]/100.
        
        sframe -= smin
        sframe *= 255. / (smax - smin)
        
        sframe = np.clip(sframe, 0, 255.)
        gray = np.require(sframe, np.uint8, 'C')

        h, w = gray.shape
    
        im = QtGui.QImage(gray.data, w, h, QtGui.QImage.Format_Indexed8)
        return QtGui.QPixmap.fromImage(im), gray

    def _cap_title(self, ndx):
        """
        format the string for titling the live or capture frame
        Returns
        -------

        """

        return '%d/%d @ %d:%02d:%02d' % (ndx, self.dpar.n_caps,
                                              self.dpar.frame_timestamp[ndx].hour,
                                              self.dpar.frame_timestamp[ndx].minute,
                                              self.dpar.frame_timestamp[ndx].second)

    def update_cap_image(self):
        """
        update the mini/capture display (or the live-screen if swapped) based on saved frames and settings
        in display param
        """

        fn = self._get_cap_filename()
        try:
            im = PIL.Image.open(fn)
        except FileNotFoundError:
            return

        frame = np.array(im)

        """
        frame = cv2.imread(fn, cv2.IMREAD_ANYDEPTH)
        if (frame is None):
            return
        """

        frame = (frame >> (16 - self.camera.pixel_bits)).astype(np.uint16)

        ndx = self.dpar.cur_cap

        if self.dpar.cap_live_swap:
            pix, gray = self._get_pixmap(frame, self.dpar.iwindow[ndx])
            self.live_screen.live_title = self._cap_title(ndx)
            self.live_screen.setPixmap(pix)
        else:
            pix, gray = self._get_pixmap(frame[::4,::4], self.dpar.iwindow[ndx])
            self.cap_screen.cap_title = self._cap_title(ndx)
            self.cap_screen.setPixmap(pix)
            self.cap_screen.format_for_cap()    # This is because first time, format is for "no stills".

    def _live_title(self, fps):
        """
        Format the live title for display.  this routine gets the actual exposure time from the camera internals.

        Parameters
        ----------
        fps : (float)
            the (smoothed)
        Returns
        -------

        """

        et = np.int(np.round(self.camera.actual_exposure_time_ms))
        return 'Live %d ms %.2f FPS' % (et, fps)


    def update_frame(self, frame):
        """
        Callback function for cameras when new frame has arrived.  This 
        centralizes the processing of data and coordination with graphical
        layouts.

        Convert the 2D numpy array `gray` into a 8-bit QImage with a gray
        colormap.  The first dimension represents the vertical image axis.
        http://www.mail-archive.com/pyqt@riverbankcomputing.com/msg17961.html
        """

        t = datetime.now()
        delta_t = t - self.dpar.frame_timestamp[0]
        fps = self.dpar.update_fps(1./delta_t.total_seconds())

        self.dpar.frame_timestamp[0] = t

        if self.config.black_correct:
            cframe = self.ffc.black_correct(frame)
        else:
            cframe = frame

        self.dpar.latest_frame = np.copy(cframe)
        
        if self.dpar.cap_live_swap:
            pix, gray = self._get_pixmap(cframe[::4,::4], self.dpar.iwindow[0])
            self.cap_screen.cap_title = self._live_title(fps)
            self.cap_screen.setPixmap(pix)
        else: 
            pix, gray = self._get_pixmap(cframe, self.dpar.iwindow[0])
            self.live_screen.live_title = self._live_title(fps)
            self.live_screen.setPixmap(pix)

        self.draw_histogram()


        if self.recording_sequence:

            # MRP ToDo update these tags properly.
            et = np.int(np.round(self.camera.actual_exposure_time_ms))
            ifi_ms = 1000. / self.camera.actual_frame_rate
            ts_ms = np.int(np.round(ifi_ms * self.seq_frame_num))

            self.ifd.update_tags((self.seq_frame_num, 0), et, 0, ts_ms, 99)

            cap_image = np.copy(self.dpar.latest_frame).astype(np.uint16)
            #cv2.imwrite(cfn, (cap_image << (16 - self.camera.pixel_bits)).astype(np.uint16))

            """
            Perform the TIFF windowing and then rebinning (compress) according to config file options
            """
            x0 = max(0, (cap_image.shape[1] - config.tiff_seq_x_window) // 2)
            x1 = cap_image.shape[1] - x0
            y0 = max(0, (cap_image.shape[0] - config.tiff_seq_y_window) // 2)
            y1 = cap_image.shape[0] - y0
            cap_image = cap_image[y0:y1, x0:x1]

            shift_bits = 16 - self.camera.pixel_bits
            if config.tiff_seq_rebin > 1:   # not tested for r ne 2
                r = config.tiff_seq_rebin
                cap_image = cap_image.reshape((cap_image.shape[0] // r, r, cap_image.shape[1] // r, -1)).sum(axis=3).sum(axis=1)
                extra_bits = 2 * (r.bit_length() -1)
                shift_bits = max(0, shift_bits - extra_bits)


            #im = PIL.Image.fromarray(gray)
            im = PIL.Image.fromarray((cap_image << shift_bits).astype(np.uint16))

            im.save(self.tiff_out, tiffinfo=self.ifd, compression=TIFF_COMPRESSION)
            self.tiff_out.newFrame()
            self.seq_frame_num += 1
            self.seq_frame_label.setText(str(self.seq_frame_num))

        if self.recording_video:
            # cframe is int16
            #f8 = ((cframe >> (self.camera.pixel_bits - 8)) & 0xff).astype(np.uint8)
            #Style 1:
            #fc = np.stack((f8, f8, f8), axis=-1)
            #self.rv_vout.write(fc)
            #Style 2&3:
            self.rv_vout.write(gray)
            self.recorded_video_frame_number += 1
            #Style 4: (16-bit)
            #self.rv_vout.write(cframe)

            #if self.recorded_video_frame_number == 20:
            #    self.record_video() # turn off

    def draw_histogram(self):
        """
        Draw the histogram and gain curve into the histogram canvas
        
        gain curve (gc) shrink factors and offsets are to make the curve
        match the slider controls
        
        Histogram and gain curve axes are normalized (0,1).  Slider settings
        and iwindows are percentages of the camera's pixel_maxval
        
        """

        hframe = self.dpar.latest_frame[::4,::4]

        gcy_shrink = 0.8
        gcy_offset = (1. - gcy_shrink)/2.
        
        gcurve_x = [0, self.dpar.iwindow[0][0]/100., self.dpar.iwindow[0][1]/100., 1.]
        gcurve_y = [gcy_offset, gcy_offset, 1.-gcy_offset, 1.-gcy_offset]

        hist, bin_edges = np.histogram(hframe.flatten(), bins=HIST_NBINS, range=(0., self.camera.pixel_maxval))
        hcurve_y = np.array(hist).astype(float) / float(max(hist))
        #hcurve_x = np.array(bin_edges).astype(float)[0:-1] / 256.
        hcurve_x = np.arange(HIST_NBINS) / HIST_NBINS


        self.hist_canvas.gain_trace.set_data(gcurve_x, gcurve_y)
        for hb,hy in zip(self.hist_canvas.hist_bars, hcurve_y):
            hb.set_height(hy)

        self.hist_canvas.draw()


    def setup_graphics_view(self):
        """
        Build the GUI.
        """
        self.main_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.main_widget)
 
        self.live_screen = LiveScreen((FRAME_HEIGHT,FRAME_WIDTH), parent = self.main_widget)

        self.cam_label = QtWidgets.QLabel()
        self.cam_label.setAlignment(Qt.AlignCenter)

        self.cap_screen = CapScreen((FRAME_HEIGHT//4,FRAME_WIDTH//4), parent = self.main_widget)

        self.hist_canvas = HistCanvas(self.main_widget, dpi=100, height=1.56, width=3.20)

        self.maxi_scrollbar = QtWidgets.QScrollBar(Qt.Horizontal, parent=self.hist_canvas)
        self.maxi_scrollbar.setRange(0, 100)
        self.maxi_scrollbar.setValue(100)
        self.maxi_scrollbar.valueChanged.connect(self.__maxi_scrollbar_callback)
        self.mini_scrollbar = QtWidgets.QScrollBar(Qt.Horizontal, parent=self.hist_canvas)
        self.mini_scrollbar.setRange(0, 100)
        self.mini_scrollbar.setValue(0)
        self.mini_scrollbar.valueChanged.connect(self.__mini_scrollbar_callback)

        self.reset_button = QtWidgets.QPushButton('Reset')
        self.reset_button.clicked.connect(self.__reset_button_callback)
        self.global_button = QtWidgets.QPushButton('Global')
        self.global_button.clicked.connect(self.__global_button_callback)
        self.roi_button = QtWidgets.QPushButton('ROI')
        self.roi_button.clicked.connect(self.__roi_button_callback)
        self.roi_button.setEnabled(False)
        self.live_screen.connect_roi_button(self.roi_button)
        self.cal_button = QtWidgets.QPushButton('Cal')
        self.cal_button.clicked.connect(self.__cal_button_callback)
        self.cal_button.setEnabled(self.config.black_correct)

        self.cap_scrollbar = QtWidgets.QScrollBar(Qt.Horizontal, parent=self.cap_screen)
        self.cap_scrollbar.valueChanged.connect(self.__cap_scrollbar_callback)
        self.cap_scrollbar.setRange(0, 0)

        self.exp1_radio = QtWidgets.QRadioButton()
        self.exp1_radio.setText('Bright')
        self.exp1_select = QtWidgets.QComboBox()
        self.exp1_ifi_select = QtWidgets.QComboBox()

        self.exp2_radio = QtWidgets.QRadioButton()
        self.exp2_radio.setText('Fluor')
        self.exp2_select = QtWidgets.QComboBox()
        self.exp2_ifi_select = QtWidgets.QComboBox()

        hbox = QtWidgets.QHBoxLayout()

        hbox.addStretch(1)
        hbox.addWidget(self.reset_button)
        hbox.addWidget(self.global_button)
        hbox.addWidget(self.roi_button)
        hbox.addStretch(1)

        gbox_cb_buttons = QtWidgets.QGroupBox(self)
        gbox_cb_buttons.setTitle('Contrast/Brightness')
        gbox_cb_buttons.setLayout(hbox)

        exp_panel = QtWidgets.QGridLayout()
        exp_panel.addWidget(self.exp1_radio, 0, 0)
        exp_panel.addWidget(self.exp1_select, 0, 1)
        exp_panel.addWidget(QtWidgets.QLabel('ms'), 0, 2)
        exp_panel.addWidget(self.exp1_ifi_select, 0, 3)
        exp_panel.addWidget(QtWidgets.QLabel('s'), 0, 4)

        exp_panel.addWidget(self.exp2_radio, 1, 0)
        exp_panel.addWidget(self.exp2_select, 1, 1)
        exp_panel.addWidget(QtWidgets.QLabel('ms'), 1, 2)
        exp_panel.addWidget(self.exp2_ifi_select, 1, 3)
        exp_panel.addWidget(QtWidgets.QLabel('s'), 1, 4)

        exp_panel.addWidget(self.cal_button, 0, 5, 2, 1)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addStretch(1)
        hbox.addLayout(exp_panel)
        hbox.addStretch(1)

        gbox_exp_controls = QtWidgets.QGroupBox()
        gbox_exp_controls.setTitle('Exposure / Inter-frame Interval')
        gbox_exp_controls.setLayout(hbox)

        """
        Add controls for the LED output signal
        """

        self.led_auto_radio = QtWidgets.QRadioButton('Auto')
        self.led_auto_radio.toggled.connect(self.__led_radio_callback)
        self.led_on_radio = QtWidgets.QRadioButton('On')
        self.led_on_radio.toggled.connect(self.__led_radio_callback)
        self.led_off_radio = QtWidgets.QRadioButton('Off')
        self.led_off_radio.toggled.connect(self.__led_radio_callback)
        self.led_state = None

        hbox = QtWidgets.QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self.led_auto_radio)
        hbox.addWidget(self.led_on_radio)
        hbox.addWidget(self.led_off_radio)
        hbox.addStretch(1)

        gbox_led_controls = QtWidgets.QGroupBox()
        gbox_led_controls.setTitle('LED Control')
        gbox_led_controls.setLayout(hbox)

        """ 
        Make the capture pallette buttons, put them in an hbox, then into a group.
        """

        ctext = QtWidgets.QLabel('Group: ')
        self.epoch_label = QtWidgets.QLabel(' ')
        clear_cap_button = QtWidgets.QPushButton('Reset')
        clear_cap_button.clicked.connect(self.__clear_cap_callback)
        self.seq_frame_label = QtWidgets.QLabel(' ')

        hbox0 = QtWidgets.QHBoxLayout()
        hbox0.addWidget(ctext)
        hbox0.addWidget(self.epoch_label)
        hbox0.addWidget(clear_cap_button)
        hbox0.addWidget(self.seq_frame_label)
        hbox0.addStretch(1)

        self.swap_button = QtWidgets.QPushButton('Swap')
        self.swap_button.clicked.connect(self.swap_cap_live)
        self.swap_button.setEnabled(False)

        self.capture_button = QtWidgets.QPushButton('Capture')
        self.capture_button.clicked.connect(self.capture)

        self.rec_seq_button = QtWidgets.QPushButton('Rec Stack')
        self.rec_seq_button.clicked.connect(self.record_sequence)
        self.rec_seq_button.setEnabled(False)

        self.rec_video_button = QtWidgets.QPushButton('Rec Video')
        self.rec_video_button.clicked.connect(self.record_video)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self.swap_button)
        hbox.addWidget(self.capture_button)
        hbox.addWidget(self.rec_seq_button)
        hbox.addWidget(self.rec_video_button)
        hbox.addStretch(1)

        vbox = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox0)
        vbox.addWidget(self.cap_screen)
        vbox.addWidget(self.cap_scrollbar)
        vbox.addLayout(hbox)

        gbox_cap_buttons = QtWidgets.QGroupBox(self)
        gbox_cap_buttons.setTitle('Capture')
        gbox_cap_buttons.setLayout(vbox)


        self.log_entry = QtWidgets.QLineEdit()
        self.log_entry.returnPressed.connect(self.__log_entry_callback)
        self.log_screen = QtWidgets.QPlainTextEdit()

        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.log_screen)
        vbox.addWidget(self.log_entry)

        gbox_log_controls = QtWidgets.QGroupBox(self)
        gbox_log_controls.setTitle('Log')
        gbox_log_controls.setLayout(vbox)

        rhs_panel = QtWidgets.QVBoxLayout()
        rhs_panel.addWidget(self.cam_label)
        rhs_panel.addWidget(self.maxi_scrollbar)
        rhs_panel.addWidget(self.hist_canvas)
        rhs_panel.addWidget(self.mini_scrollbar)
        rhs_panel.addWidget(gbox_cb_buttons)
        rhs_panel.addWidget(gbox_exp_controls)
        rhs_panel.addWidget(gbox_led_controls)
        #rhs_panel.addWidget(self.cap_screen)
        #rhs_panel.addWidget(self.cap_scrollbar)
        rhs_panel.addWidget(gbox_cap_buttons)
        rhs_panel.addWidget(gbox_log_controls)
        rhs_panel.addStretch(1)
        
        lr = QtWidgets.QHBoxLayout(self.main_widget)
        lr.setSpacing(1)
        lr.setContentsMargins(0, 0, 0, 0)
        
        lr.addWidget(self.live_screen)
        lr.addLayout(rhs_panel)
        lr.addStretch(1)

    def closeEvent(self, event):
        if self.camera is not None:
            self.camera.stop_sampling()
            self.camera.release()

    def __led_radio_callback(self, checked):
        if not checked: return
        if self.led_auto_radio.isChecked():
            self.camera.led_state('AUTO')
        if self.led_on_radio.isChecked():
            self.camera.led_state('ON')
        if self.led_off_radio.isChecked():
            self.camera.led_state('OFF')


    def __log_entry_callback(self):
        self.write_to_log(self.log_entry.text())
        self.log_entry.clear()


    def __clear_cap_callback(self):


        self.dpar.clear_caps()
        self.cap_scrollbar.setRange(0, 0)
        self.cap_scrollbar.setValue(0)
        self.timestamp.reset()
        self.cap_screen.reset()
        self.swap_button.setEnabled(False)


    def record_video(self):
        """

        Returns
        -------

        """
        if not self.recording_video:  # so we are going to switch to recording mode.

            self.rec_video_button.setStyleSheet("background-color:lime")
            self.capture_button.setEnabled(False)
            self.rec_seq_button.setEnabled(False)

            fn = self._get_video_filename()
            vfn = os.path.basename(fn)
            self.recorded_video_frame_number = 0

            fps = self.dpar.fps_estimate

            """
            Style 1 works but is likely not efficient.
            """
            #Style 1: DIVX, color
            #self.rv_vout = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc('D', 'I', 'V', 'X'),
            #                               fps=10, frameSize=, isColor=True)
            #Style 2: DIVX, monochrome
            #self.rv_vout = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc('D', 'I', 'V', 'X'),
            #                               fps=10, frameSize=FRAME_SHAPE, isColor=False)

            #Style 3: FFV1 (lossless), monochrome. Use VLC media player.
            self.rv_vout = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc(*VIDEO_FORMAT),
                                           fps=fps, frameSize=(FRAME_WIDTH, FRAME_HEIGHT), isColor=False)

            ifi_ms = self.camera.ifi_settings[self.camera.current_ifi_index]

            et = np.int(np.round(self.camera.actual_exposure_time_ms))

            self.write_to_log('Video Recording Started, %s' % vfn)
            self.write_to_log('IFI %d ms, fps = %.3f' % (ifi_ms, fps))
            self.write_to_log('Exposure %d ms' % et)
            self.recording_video = True

        else:
            self.rec_video_button.setStyleSheet("")
            self.capture_button.setEnabled(True)
            self.rec_seq_button.setEnabled(True if self.camera.current_ifi_index > 0 else False)

            self.rv_vout.release()
            self.write_to_log('Video Recording Stopped, %d Frames' % self.recorded_video_frame_number)


            self.recording_video = False

    def record_sequence(self):
        """
        Called to initiate or terminate recording mode.  A tricky sequence:
        - initially, if we are about to start recording, perform a capture and then set the
          exposure.  This will reset internal timers so that capturing becomes synchronized with
          the button push, instead being randomly phased.
        - next, toggle it to start/stop recording.
        - finally, change the record button graphics.
        - the flag being set or cleared is what controls whether or not frames are written to
          files during update_frame
        Parameters
        ----------
        kill

        Returns
        -------

        """
        if not self.recording_sequence:  # so we are going to switch to recording mode.

            self.rec_seq_button.setStyleSheet("background-color:lime")
            self.capture_button.setEnabled(False)


            tiffname = self._get_seq_filename()
            tfn = os.path.basename(tiffname)

            ifi_ms = self.camera.ifi_settings[self.camera.current_ifi_index]
            ifi_s = ifi_ms/ 1000.
            self.write_to_log('Stack Recording Started, %s, IFI = %g s' % (tfn,ifi_s))
            self.select_exposure() # re-select, just to synchronize

            self.seq_frame_num = 0
            self.seq_frame_label.setText('0')
            self.ifd = doriclib.DoricImageFileDirectory(0)
            self.tiff_out = PTIP.AppendingTiffWriter(tiffname, True)

            self.recording_sequence = True

        else:
            self.rec_seq_button.setStyleSheet("")
            self.capture_button.setEnabled(True)

            self.write_to_log('Stack recording stopped, %d frames.' % self.seq_frame_num)
            self.seq_frame_label.setText(' ')

            self.recording_sequence = False
            self.tiff_out.close()


    def _update_scrollbars(self):
        self.mini_scrollbar.setValue(self.dpar.iwindow[0][0])
        self.maxi_scrollbar.setValue(self.dpar.iwindow[0][1])


    def __maxi_scrollbar_callback(self, value):
        mini = self.dpar.iwindow[0][0]+1.
        if value <  mini:
            self.maxi_scrollbar.setValue(mini)
        else:
            self.dpar.iwindow[0][1] = value

    def __mini_scrollbar_callback(self, value):
        maxi = self.dpar.iwindow[0][1]-1
        if value >  maxi:
            self.mini_scrollbar.setValue(maxi)
        else:
            self.dpar.iwindow[0][0] = value

    def __reset_button_callback(self):
        self.dpar.iwindow[0] = [0., 100.]
        self._update_scrollbars()

    def __cal_button_callback(self):

        reply = QtWidgets.QMessageBox.question(self, 'Black Calibration',
                                               'Darken field and press OK to continue',
                                               QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.Ok)

        if reply == QtWidgets.QMessageBox.Ok:
            self.ffc.start_black_cal()

    def _set_contrast(self, f):            
        scl = 100. / self.camera.pixel_maxval
        mn = f.min() * scl
        mx = f.max() * scl
        self.dpar.iwindow[0] = [mn, mx]
        self._update_scrollbars()

    def __global_button_callback(self):
        self._set_contrast(self.dpar.latest_frame)
        
    def __roi_button_callback(self):
        mask = self.live_screen.roi_mask()
        if mask is not None:
            self._set_contrast(self.dpar.latest_frame[mask])

    def __cap_scrollbar_callback(self, value):
        self.dpar.cur_cap = value
        self.update_cap_image()
        pass


def first_time_run():
    """
    Perform file-related setup operations on first program invocation.

    Copying the INI template:
        - skip over the first two lines in the template
        - write alternate two informational lines to the INI file
        - write the DEFAULT section heading and variable definitions for ProgramName and UserHome
        - copy, line by line, the rest of the template file.

    Write the batch file:
        - write two informational lines as comments (REM)
        - write DOS commands to invoke the python interpreter with this as target and an argument that is copied
          from this invocation
    Returns
    -------
    none
    """
    print('First time run - initializing...')

    if not os.path.isdir(USER_PROG_HOME_DIR):  # this will be used for both the INI file and BAT file
        os.makedirs(USER_PROG_HOME_DIR)

    con_tmp = open(CONFIG_TEMPLATE, 'r')
    con_new = open(CONFIG_FILENAME, 'w')
    line = con_tmp.readline()  # skip over first two lines
    line = con_tmp.readline()  # ...

    con_new.write('# ' + __PROGRAM_NAME__ + 'V%s' % __VERSION__ + ' Configuration File\n')
    con_new.write('# Creation: ' + time.strftime('%m/%d/%y') + '\n')

    con_new.write('[DEFAULT]\n')
    con_new.write('ProgramName = ' + __PROGRAM_NAME__ + '\n')
    #con_new.write('UserHome = ' + USER_HOME_DIR.replace('\\', '/') + '\n')
    con_new.write('UserHome = ' + USER_HOME_DIR + '\n')
    for line in con_tmp:
        con_new.write(line)
    con_tmp.close()
    con_new.close()

    print('Writing %s' % CONFIG_FILENAME)

    bat_new = open(BAT_FILENAME, 'w')
    bat_new.write('REM ' + __PROGRAM_NAME__ + 'V%s' % __VERSION__ + ' Program Launch File\n')
    bat_new.write('REM Creation: ' + time.strftime('%m/%d/%y') + '\n')
    bat_new.write('cd ' + PACKAGE_DIR + '\n')
    bat_new.write('python ' +  __PROGRAM_NAME__ + '.py ' + ' '.join(sys.argv[1:]) + '\n')
    bat_new.close()

    print('Writing %s' % BAT_FILENAME)

class GetConfig():

    def __init__(self):

        """
        First time the program is run, detected by the absence of the .ini file.  In this case, just copy the init
        template (.000) then exit.
        """
        if not os.path.isfile(CONFIG_FILENAME):
            first_time_run()
            raise SystemExit()

        """
        Init file is present, read and parse it:
        """
        conf = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation(), inline_comment_prefixes='#')
        conf.read(CONFIG_FILENAME)
        """
        Process certain paths:
        """

        path = conf['Paths']
        self.ffc_dir = path['FlatFieldCalDir']
        self.capture_dir = path['CaptureDir']
        self.image_dir = path['ImageDir']

        """
        Process options
        """

        self.cal_auto_save = conf.getboolean('Options', 'CalAutoSave', fallback=True)
        self.cal_auto_load = conf.getboolean('Options', 'CalAutoLoad', fallback=True)
        self.sound_on_capture = conf.getboolean('Options', 'SoundOnCapture', fallback=True)
        self.exp_init1 = conf.getint('Options', 'ExpInit1', fallback=100)
        self.exp_init2 = conf.getint('Options', 'ExpInit2', fallback=100)
        self.black_correct = conf.getboolean('Options', 'BlackCorrect', fallback=True)
        # Setup square window, default of full-screen height
        self.tiff_seq_x_window = conf.getint('Options', 'TiffSeqXWindow', fallback=cameras.FRAME_HEIGHT)
        self.tiff_seq_y_window = conf.getint('Options', 'TiffSeqYWindow', fallback=cameras.FRAME_HEIGHT)
        self.tiff_seq_rebin = conf.getint('Options', 'TiffSeqRebin', fallback = 2)

def _psetup():
    parser = argparse.ArgumentParser(prog=__PROGRAM_NAME__, description='Patch Clamp Microscopy Camera Interface')
    parser.add_argument('mode', type=int, default = None, help='Mode, 0=UC480, 1=WebCam, 2=Pseudo random noise')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s {version}'.format(version=__VERSION__))

    return parser


if __name__ == "__main__":

    config = GetConfig()

    args = _psetup().parse_args()

    app = QtWidgets.QApplication(sys.argv)

    main_window = Viewer(config, args.mode)
    main_window.move(10, 1)        # a good place to start for now
    main_window.show()
    app.exec_()
