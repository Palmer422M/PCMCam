# -*- coding: utf-8 -*-
"""
Created on Thu May 19 15:02:34 2016

@author: mpalmer
"""
import cv2
from PyQt5 import QtCore

import uc480
import uc480_H as H
import numpy as np

FRAME_WIDTH = 1280
FRAME_HEIGHT = 1024
FRAME_BITS_PER_PIXEL = 16
COLOR_MODE = H.IS_CM_MONO10

"""
Dfinitions for Camera parent and subclasses

Each camera is defined here.  
"""


class Camera(object):
    """ Base class for camera objects.
    """

    def __init__(self):
        self.dev_list = None
        self.uses_messages = False
        self.uses_timer = False
        self.timer = None  # needed to mute initial calls
        self.pixel_bits = 8
        self.pixel_maxval = 2**self.pixel_bits  # Class must define and maintain this.
        self.exposure_settings = ( 20, 28, 40, 57, 80, 100, 140, 200, 280, 400, 570, 800, 1000, 1400, 2000, 2800, 4000)
        self.black_cal_averages = (20, 28, 10, 10, 10,  10,  10,  10,  10,   5,   5,   5,    4,    2,    2,    1,    1)
        self.default_exposure_index = 5
        self.current_exposure_index = self.default_exposure_index
        self.actual_exposure_time_ms = 0.
        self.actual_frame_rate = 0.
        self.cal_active = False

    def set_cal_state(self, cal_on):
        """
        Called by program to notify the camera that a calibration is about to start (cal_on = True), or has ended
        (cal_on = False).

        Returns
        -------
        (none)
        """
        self.cal_active = cal_on

    def connect(self, win_id):
        pass

    def set_exposure(self, exp_ndx):
        pass

    def start_sampling(self, uf_callback):
        pass

    def msg_event(self, msg):
        return False, 0  # Signal that message was not handled.

    def stop_sampling(self):
        pass

    def release(self):
        pass


class UC480_Camera(Camera):
    def __init__(self):
        super().__init__()
        self.dev_list = uc480.device_lookup()
        self.uses_messages = True
        # (fps, etms, navg)
        self.exp_param = ((5., 20., 1),
                          (5., 28., 1),
                          (5., 40., 1),
                          (5., 57., 1),
                          (5., 80., 1),
                          (5., 100., 1),
                          (5., 140., 1),
                          (5., 200., 1),
                          (3.5, 280., 1),
                          (2.5, 400., 1),
                          (1.7, 570., 1),
                          (1.2, 800., 1),
                          (1.0, 1000., 1),
                          (0.7, 1400., 1),
                          (0.5, 2000., 1),
                          (0.7, 1400., 2),
                          (0.5, 2000., 2))
        assert len(self.exp_param) == len(self.exposure_settings)
        self.max_max_frame = max([ep[2] for ep in self.exp_param])
        self.frame_ptr = 0

        """
        Internal buffer for this camera only. Needed for the longer exposure times
        """
        self.frame = np.zeros((self.max_max_frame, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.int16, order='C')

        self.pixel_bits = 10       # 10-bit i/f mode
        self.pixel_maxval = 2**self.pixel_bits


    def connect(self, win_id):

        self.api = uc480.Camera(self.dev_list[0][0])

        self.api.setup_memory(FRAME_WIDTH, FRAME_HEIGHT, FRAME_BITS_PER_PIXEL)
        self.api.SetColorMode(COLOR_MODE)

        pc = self.api.set_min_pixel_clock()
        #print('Pixel Clock (MHz):', pc)

        self.set_exposure(self.default_exposure_index)

        """
        ft, ftmin, ftmax, ftint = self.api.get_frame_time_settings()
        print('FT:', ft, ftmin, ftmax, ftint)

        et, etmin, etmax, etinc = self.api.get_exposure_settings()
        print('ET: ', et, etmin, etmax, etinc)
        """

        """
        # change frame rate and see effect on exp time.  Result, no change.
        # need to update, optimize exposure time after frame rate chnage.
        # max frame time at 7 MHz pixel clock is 2 s.
        newfps = self.api.SetFrameRate(1.0)
        print('FPS2: ', newfps)

        et, etmin, etmax, etinc = self.api.get_exposure_settings()
        print('ET2: ', et, etmin, etmax, etinc)

        newfps = self.api.SetFrameRate(5.0)
        print('FPS3: ', newfps)

        exp_time = 0 # to set the max
        et = self.api.set_exposure(exp_time)
        print('Exposure time (ms) 3: ', et)
        """

        self.api.EnableMessage(H.IS_FRAME, win_id)

    def start_sampling(self, uf_callback):
        self.uf_callback = uf_callback
        self.api.CaptureVideo()

    def set_exposure(self, new_ndx):
        self.current_exposure_index = new_ndx
        ep = self.exp_param[new_ndx]

        self.actual_frame_rate = self.api.SetFrameRate(ep[0])
        #print('FPS: ', newfps)

        cam_exp = self.api.set_exposure(ep[1])
        self.actual_exposure_time_ms = cam_exp * ep[2]
        #print('Exposure time (ms): ', et)

        self.frame_ptr = 0

    def msg_event(self, msg):
        if msg.message == H.IS_UC480_MESSAGE:
            if (msg.wParam == H.IS_FRAME):
                # print('msg = %x, %x, %x' % (msg.message, msg.lParam, msg.wParam))
                self._update_image()
                return True, 0

        return False, 0

    def stop_sampling(self):
        self.api.DisableMessage(H.IS_FRAME)  # deactivate message
        self.api.StopLiveVideo(wait=H.IS_FORCE_VIDEO_STOP)  # trying this???

    def release(self):
        self.api.cleanup()

    def _update_image(self):

        dest = self.frame[self.frame_ptr]
        self.api.get_frame(dest)

        self.frame_ptr += 1
        max_frame = self.exp_param[self.current_exposure_index][2]
        if self.frame_ptr >= max_frame:
            self.frame_ptr = 0
            if max_frame == 1:
                f = self.frame[0, :, :] # no need to sum and clip if only one (most often)
            else:
                f = np.clip(np.sum(self.frame[0:max_frame, :, :], axis=0, dtype=np.int16), 0, self.pixel_maxval)
            self.uf_callback(f)


class Pseudo_Camera(Camera):
    """
    A pseudo camera to generate images squences for testing.
    """

    def __init__(self):
        super().__init__()
        self.dev_list = [(0, 'Pseudo', 'S/N')]
        self.uses_timer = True

    def start_sampling(self, uf_callback):
        self.uf_callback = uf_callback

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.__tick_callback)
        self.timer.start(self.exposure_settings[self.current_exposure_index])

    def set_exposure(self, exp_ndx):
        self.current_exposure_index = exp_ndx
        if self.timer is not None:
            self.timer.setInterval(self.exposure_settings[exp_ndx])
        self.actual_exposure_time_ms = self.exposure_settings[exp_ndx]

    def __tick_callback(self):
        """
        timer-driven call-back.
        """
        if self.cal_active:
            si = np.empty((FRAME_HEIGHT, FRAME_WIDTH), dtype=np.int16)
            si.fill(10)
        else:
            s = np.random.normal(128., 10., (FRAME_HEIGHT, FRAME_WIDTH))
            si = s.astype(np.int16)
            si[100:160, 100:160] -= 50
            si[600:680, 700:800] += 50

        self.uf_callback(si)


class Web_Camera(Camera):
    def __init__(self):
        super().__init__()
        self.dev_list = [(0, 'web', 'S/N')]
        self.uses_timer = True

    def connect(self, win_id):
        self.api = cv2.VideoCapture(self.dev_list[0][0])
        # fps = 20.
        # self.api.set(cv2.CAP_PROP_FPS, fps)

    def start_sampling(self, uf_callback):
        self.uf_callback = uf_callback

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.__tick_callback)
        self.timer.start(self.exposure_settings[self.current_exposure_index])

    def set_exposure(self, exp_ndx):
        self.current_exposure_index = exp_ndx
        self.api.set(cv2.CAP_PROP_FPS, 1000. / self.exposure_settings[exp_ndx])
        if self.timer is not None:
            self.timer.setInterval(self.exposure_settings[exp_ndx])

    def __tick_callback(self):
        """
        Defined to cause timer-driven call.
        
        This is the web-cam simulator.  Increase the frame size to 1280 x 1024
        and sum the color channels to simulate scientific camearas.
        """

        rval, frame = self.api.read()
        f = np.sum(frame, axis=2, dtype=np.uint16) // 3
        h, w = f.shape
        fbig = np.ndarray((1024, 1280), np.uint16)
        fbig.fill(128 * 3)
        fbig[0:h, 0:w] = f
        fbig[1024 - h:, 1280 - w:] = f[::-1, ::-1]
        self.uf_callback(fbig)

    def stop_sampling(self):
        pass

    def release(self):
        self.api.release()
