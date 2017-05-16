"""
PCMicro - Patch Clamp Microscope Camera Software.

Command line script.  Works with Python 3.5, Qt5. 
Created April 2016 by Matthew Palmer.
Developed from glue code and test in pydcu - bernardokyotoku.  At https://github.com/bernardokyotoku/pydcu

Some updates.

"""
import sys
import os
import configparser
import time
import ctypes

from PyQt5 import QtCore, QtWidgets, QtGui, QtMultimedia
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
from screens import CapScreen, LiveScreen


"""
Global parameters:
"""


GAIN_TRACE_COLOR = 'r' # Matplotlib color
HIST_TRACE_COLOR = 'b'
HIST_NBINS = 64

FPS_AVERAGES = 5

FRAME_WIDTH = cameras.FRAME_WIDTH
FRAME_HEIGHT = cameras.FRAME_HEIGHT
FRAME_SHAPE = (FRAME_HEIGHT, FRAME_WIDTH)

AUTHOR = "Palmer"
PROG_NAME = 'PCMCam'
PROG_VERSION = 1
PROG_SUBVERSION = 0

PROG_APP_ID = '%s.%s.%d.%d' % (AUTHOR, PROG_NAME, PROG_VERSION, PROG_SUBVERSION)

PACKAGE_DIR = os.path.split(os.path.realpath(__file__))[0]
USER_HOME_DIR = os.path.expanduser("~")
USER_PROG_HOME_DIR = os.path.join(USER_HOME_DIR, PROG_NAME)

MEDIA_DIR = os.path.join(PACKAGE_DIR, 'media')

PROG_ICON_FILE = os.path.join(MEDIA_DIR, 'patch_icon.ico')
CAMERA_CLICK_FILE = os.path.join(MEDIA_DIR, 'camera.wav')

CONFIG_FILENAME = os.path.join(USER_PROG_HOME_DIR, PROG_NAME) + '.ini'
CONFIG_TEMPLATE = os.path.join(PACKAGE_DIR, PROG_NAME) + '.000'
BAT_FILENAME = os.path.join(USER_PROG_HOME_DIR, PROG_NAME) + '.bat'

PROG_LOAD_TIMESTAMP = datetime.now()


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
        self.hold_exp_ind = 0 # copy of currently set exposure index
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
        self.hold_exp_ind = self.camera.current_exposure_index # for later restoration
        self.frame_ind = 0 # frame counter
        self.exp_ind = 0 # exposure index counter (for cycling)
        self.prior_black = np.copy(self.black[0])
        self.black[0].fill(0) # because black integrates frames during cal sequence.
        self.discard_next = True
        self.camera.set_cal_state(True) # notify the camera api in case it needs to know we are calibrating
        self.camera.set_exposure(self.exp_ind)
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
            self.camera.set_exposure(self.exp_ind)

        self.update_progress()

    def stop_cal(self):
        self.camera.set_exposure(self.hold_exp_ind)
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
        self.frame = [None]          # stack of live then captured frames
        self.frame_timestamp = [datetime.now()]
        self.n_caps = 0
        self.cur_cap = None          # current capture that's displayed
        self.cap_live_swap = False   # true when live and capture screens are swapped
        self.fps_history = []
        self.iwindow_toggle_save = [0., 100.] # place to store windows values across exp-toggling

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

        return np.mean(self.fps_history)


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

        #l = Line2D([], [], color=GAIN_TRACE_COLOR)
        #self.gain_trace = self.axes.add_line(l)

        self.gain_graph = self.axes.plot([0, 1.], [0, 1.], color = HIST_TRACE_COLOR)


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
        self.setWindowTitle('%s %d.%d' % (PROG_NAME, PROG_VERSION, PROG_SUBVERSION))

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
        self.ffc = FlatFieldCal(self)
        self.dpar.iwindow = [[0., 100.]]

        self.exp1_select.addItems([str(e) for e in self.camera.exposure_settings])
        ndx = _closest(self.camera.exposure_settings, self.config.exp_init1)
        self.exp1_select.setCurrentIndex(ndx)
        self.exp1_select.currentIndexChanged.connect(self.__exp1_changed_callback)

        self.camera.set_exposure(ndx)

        self.exp2_select.addItems([str(e) for e in self.camera.exposure_settings])
        ndx = _closest(self.camera.exposure_settings, self.config.exp_init2)
        self.exp2_select.setCurrentIndex(ndx)
        self.exp2_select.currentIndexChanged.connect(self.__exp2_changed_callback)

        self.exp1_radio.setChecked(True)
        self.exp1_radio.toggled.connect(self.select_exposure)

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
                self.swap_cap_live()

            if event.key() == Qt.Key_C:
                self.capture()

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

    def __exp1_changed_callback(self, ndx):
        """
        Callback for exposure 1 (bright) drop-down

        Parameters
        ----------
        ndx : index of currently selected item.

        Returns
        -------

        """
        self.exp1_radio.setChecked(True)
        self.camera.set_exposure(ndx)

    def __exp2_changed_callback(self, ndx):
        """
        Callback for exposure 2 (fluoro) drop-down

        Parameters
        ----------
        ndx : index of currently selected item.

        Returns
        -------

        """
        self.exp2_radio.setChecked(True)
        self.camera.set_exposure(ndx)

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

        if exp1_selected:   # then exp1
            self.camera.set_exposure(self.exp1_select.currentIndex())
        else:
            self.camera.set_exposure(self.exp2_select.currentIndex())

        temp = list(self.dpar.iwindow_toggle_save)
        self.dpar.iwindow_toggle_save = list(self.dpar.iwindow[0])
        self.dpar.iwindow[0] = temp
        self._update_scrollbars()

    def swap_cap_live(self):
        """
        Swap the roles of the Live screen and capture palette.

        Returns
        -------
        none
        """

        if self.dpar.cur_cap is None:
            return
        self.dpar.cap_live_swap = not self.dpar.cap_live_swap

        if self.dpar.cap_live_swap:
            self.live_screen.format_for_cap()
            self.cap_screen.format_for_live()
        else:
            self.live_screen.format_for_live()
            self.cap_screen.format_for_cap()

        self.update_cap_image()

    def capture(self):
        """
        Perform a capture operation.

        The process is as follows:
            * make a copy of the most recent live frame (dpar.frame[0]).
            * append this, the window settings, and a timestamp to the respective lists in self.dpar
            * play a sound (if configured to do so)
            * write this capture to a file (autosave) if configured to do so.
            * update the capture palette (titles, colors...)

        Returns
        -------

        """
        self.dpar.n_caps += 1
        self.cap_screen.cap_loaded = True
        cap_image = np.copy(self.dpar.frame[0]).astype(np.uint16)
        tstamp = datetime.now()

        self.dpar.cur_cap = self.dpar.n_caps
        self.dpar.frame.append(cap_image)
        self.dpar.iwindow.append(list(self.dpar.iwindow[0]))  # deep copy
        self.dpar.frame_timestamp.append(tstamp)

        self.cap_scrollbar.setRange(1, self.dpar.n_caps)
        self.cap_scrollbar.setValue(self.dpar.n_caps)

        if self.config.sound_on_capture:
            QtMultimedia.QSound.play(CAMERA_CLICK_FILE)

        if self.config.capture_auto_save:
            """
            Write the capture to a file.  Create the daily capture directory if not yet created.
            """
            fnd = os.path.join(self.config.capture_dir, PROG_LOAD_TIMESTAMP.strftime('c%Y-%m-%d'))
            if not os.path.isdir(fnd):
                os.makedirs(fnd)
            fn = os.path.join(fnd, 'c' + PROG_LOAD_TIMESTAMP.strftime('%H%M%S') + '_%3.3d.tif' % self.dpar.n_caps)
            cv2.imwrite(fn, cap_image << (16 - self.camera.pixel_bits))

            print('Writing: ', fn)

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
        return QtGui.QPixmap.fromImage(im)

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

        ndx = self.dpar.cur_cap
        if self.dpar.cap_live_swap:
            f = self.dpar.frame[ndx]
            pix = self._get_pixmap(f, self.dpar.iwindow[ndx])
            self.live_screen.live_title = self._cap_title(ndx)
            self.live_screen.setPixmap(pix)
        else:
            f = self.dpar.frame[ndx][::4,::4]
            pix = self._get_pixmap(f, self.dpar.iwindow[ndx])
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

        return 'Live %d ms %.1f FPS' % (self.camera.actual_exposure_time_ms, fps)


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

        cframe = self.ffc.black_correct(frame)

        self.dpar.frame[0] = np.copy(cframe)
        
        if self.dpar.cap_live_swap:
            pix = self._get_pixmap(cframe[::4,::4], self.dpar.iwindow[0])
            self.cap_screen.cap_title = self._live_title(fps)
            self.cap_screen.setPixmap(pix)
        else: 
            pix = self._get_pixmap(cframe, self.dpar.iwindow[0])
            self.live_screen.live_title = self._live_title(fps)
            self.live_screen.setPixmap(pix)
        
        self.draw_histogram(cframe)

    def draw_histogram(self, frame):
        """
        Draw the histogram and gain curve into the histogram canvas
        
        gain curve (gc) shrink factors and offsets are to make the curve
        match the slider controls
        
        Histogram and gain curve axes are normalized (0,1).  Slider settings
        and iwindows are percentages of the camera's pixel_maxval
        
        """

        gcy_shrink = 0.8
        gcy_offset = (1. - gcy_shrink)/2.
        
        gcurve_x = [0, self.dpar.iwindow[0][0]/100., self.dpar.iwindow[0][1]/100., 1.]
        gcurve_y = [gcy_offset, gcy_offset, 1.-gcy_offset, 1.-gcy_offset]

        hist, bin_edges = np.histogram(frame[::2,::2].flatten(), bins=HIST_NBINS, range=(0., self.camera.pixel_maxval))
        hcurve_y = np.array(hist).astype(float) / float(max(hist))
        #hcurve_x = np.array(bin_edges).astype(float)[0:-1] / 256.
        hcurve_x = np.arange(HIST_NBINS) / HIST_NBINS


        self.hist_canvas.axes.clear()
        self.hist_canvas.axes.plot(gcurve_x, gcurve_y, color = GAIN_TRACE_COLOR)
        self.hist_canvas.axes.bar(hcurve_x, hcurve_y, color = HIST_TRACE_COLOR, width=1./HIST_NBINS)
        self.hist_canvas.axes.axis([0., 1., 0., 1.])
        self.hist_canvas.figure.canvas.draw()

        #self.hist_canvas.hist_trace.set_data(hcurve_x, hcurve_y)
        # would rather use set_data but can't easily construct equivalent for bar charts.
        #self.hist_canvas.gain_trace.set_data(gcurve_x, gcurve_y)
        #self.hist_canvas.draw()



    def setup_graphics_view(self):
        """
        Build the GUI.
        """
        self.main_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.main_widget)
 
        gray = np.ndarray((FRAME_HEIGHT,FRAME_WIDTH), dtype=np.uint8)
        gray.fill(100)
        im = QtGui.QImage(gray.data, gray.shape[1], gray.shape[0], QtGui.QImage.Format_Indexed8)
        pix = QtGui.QPixmap.fromImage(im)

        self.live_screen = LiveScreen(parent = self.main_widget)
        self.live_screen.setPixmap(pix)

        gray = np.ndarray((FRAME_HEIGHT//4,FRAME_WIDTH//4), dtype=np.uint8)
        gray.fill(180)
        im = QtGui.QImage(gray.data, gray.shape[1], gray.shape[0], QtGui.QImage.Format_Indexed8)
        pix = QtGui.QPixmap.fromImage(im)

        self.cam_label = QtWidgets.QLabel()
        self.cam_label.setAlignment(Qt.AlignCenter)

        self.cap_screen = CapScreen(parent = self.main_widget)
        self.cap_screen.setPixmap(pix)

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

        self.cap_scrollbar = QtWidgets.QScrollBar(Qt.Horizontal, parent=self.cap_screen)
        self.cap_scrollbar.valueChanged.connect(self.__cap_scrollbar_callback)
        self.cap_scrollbar.setRange(0, 0)

        self.exp1_radio = QtWidgets.QRadioButton()
        self.exp1_radio.setText('Bright')
        self.exp1_select = QtWidgets.QComboBox()

        self.exp2_radio = QtWidgets.QRadioButton()
        self.exp2_radio.setText('Fluor')
        self.exp2_select = QtWidgets.QComboBox()

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
        exp_panel.addWidget(self.exp2_radio, 1, 0)
        exp_panel.addWidget(self.exp2_select, 1, 1)
        exp_panel.addWidget(QtWidgets.QLabel('ms'), 0, 2)
        exp_panel.addWidget(QtWidgets.QLabel('ms'), 1, 2)

        exp_panel.addWidget(self.cal_button, 0, 3, 2, 1)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addStretch(1)
        hbox.addLayout(exp_panel)
        hbox.addStretch(1)

        gbox_exp_controls = QtWidgets.QGroupBox()
        gbox_exp_controls.setTitle('Exposure')
        gbox_exp_controls.setLayout(hbox)

        self.capture_button = QtWidgets.QPushButton('Capture')
        self.capture_button.clicked.connect(self.capture)
        self.swap_button = QtWidgets.QPushButton('Swap')
        self.swap_button.clicked.connect(self.swap_cap_live)
        self.swap_button.setEnabled(False)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self.capture_button)
        hbox.addWidget(self.swap_button)
        hbox.addStretch(1)

        gbox_cap_buttons = QtWidgets.QGroupBox(self)
        gbox_cap_buttons.setTitle('Capture Palette')
        gbox_cap_buttons.setLayout(hbox)

        rhs_panel = QtWidgets.QVBoxLayout()
        rhs_panel.addWidget(self.cam_label)
        rhs_panel.addWidget(self.maxi_scrollbar)
        rhs_panel.addWidget(self.hist_canvas)
        rhs_panel.addWidget(self.mini_scrollbar)
        rhs_panel.addWidget(gbox_cb_buttons)
        rhs_panel.addWidget(gbox_exp_controls)
        rhs_panel.addWidget(self.cap_screen)
        rhs_panel.addWidget(self.cap_scrollbar)
        rhs_panel.addWidget(gbox_cap_buttons)
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
        self._set_contrast(self.dpar.frame[0])
        
    def __roi_button_callback(self):
        mask = self.live_screen.roi_mask()
        if mask is not None:
            self._set_contrast(self.dpar.frame[0][mask])

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

    con_new.write('# ' + PROG_NAME + 'V%d.%d' % (PROG_VERSION, PROG_SUBVERSION) + ' Configuration File\n')
    con_new.write('# Creation: ' + time.strftime('%m/%d/%y') + '\n')

    con_new.write('[DEFAULT]\n')
    con_new.write('ProgramName = ' + PROG_NAME + '\n')
    #con_new.write('UserHome = ' + USER_HOME_DIR.replace('\\', '/') + '\n')
    con_new.write('UserHome = ' + USER_HOME_DIR + '\n')
    for line in con_tmp:
        con_new.write(line)
    con_tmp.close()
    con_new.close()

    print('Writing %s' % CONFIG_FILENAME)

    bat_new = open(BAT_FILENAME, 'w')
    bat_new.write('REM ' + PROG_NAME + 'V%d.%d' % (PROG_VERSION, PROG_SUBVERSION) + ' Program Launch File\n')
    bat_new.write('REM Creation: ' + time.strftime('%m/%d/%y') + '\n')
    bat_new.write('cd ' + PACKAGE_DIR + '\n')
    bat_new.write('python ' +  PROG_NAME + '.py ' + ' '.join(sys.argv[1:]) + '\n')
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
        self.capture_auto_save = conf.getboolean('Options', 'CaptureAutoSave', fallback=True)
        self.sound_on_capture = conf.getboolean('Options', 'SoundOnCapture', fallback=True)
        self.exp_init1 = conf.getint('Options', 'ExpInit1', fallback=100)
        self.exp_init2 = conf.getint('Options', 'ExpInit2', fallback=100)

if __name__ == "__main__":

    config = GetConfig()

    if len(sys.argv) < 2:
        print('Usage: PCMCam {0, 1, 2}')
        print('     with 0=UC480, 1=WebCam, 2=Pseudo random noise')
        raise SystemExit()

    app = QtWidgets.QApplication(sys.argv)

    main_window = Viewer(config, sys.argv[1])
    main_window.move(10, 1)        # a good place to start for now
    main_window.show()
    app.exec_()
