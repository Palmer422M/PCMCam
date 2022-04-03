# -*- coding: utf-8 -*-
"""
Created on Thu May 19 15:02:34 2016

@author: mpalmer
"""

import ueye_util as uu

import cv2
from PyQt5 import QtCore
import numpy as np
from pyueye import ueye

from ctypes import sizeof, c_char_p, byref
from ctypes.wintypes import INT, UINT, DOUBLE, HWND

# Don't remember how I got these:
WM_USER = 0x400
UC480_MESSAGE = WM_USER + 0x0100

FRAME_WIDTH = 1280
FRAME_HEIGHT = 1024
FRAME_BITS_PER_PIXEL = 16

COLOR_MODE = ueye.IS_CM_MONO10

UC480_PIXEL_CLOCK_TO_USE = 24  # Note - not all values allowed.  This allows frames up to 1.27 s.

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
        #self.ifi_settings = (0, 500, 1000, 2000, 5000, 10000, 20000, 60000) # current limit
        # 6/4/19: Tried 100 ms but system (HP laptop) crashes.  200 seems to work.
        self.ifi_settings = (0, 200, 500, 1000, 2000, 5000, 10000, 20000, 60000) # current limit
        self.exposure_settings = ( 20, 28, 40, 57, 80, 100, 140, 200, 280, 400, 570, 800, 1000, 1400, 2000, 2800, 4000)
        self.black_cal_averages = (20, 28, 10, 10, 10,  10,  10,  10,  10,   5,   5,   5,    4,    2,    2,    1,    1)
        self.default_exposure_index = 5
        self.current_exposure_index = self.default_exposure_index
        self.current_ifi_index = 0
        self.actual_exposure_time_ms = 0.
        self.actual_frame_rate = 1.
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

    def set_exposure(self, exp_ndx, ifi_ndx):
        pass

    def start_sampling(self, uf_callback):
        pass

    def msg_event(self, msg):
        return False, 0  # Signal that message was not handled.

    def stop_sampling(self):
        pass

    def release(self):
        pass

    def led_state(self, state):
        pass


class UC480_Camera(Camera):
    def __init__(self):
        super().__init__()

        self.hCam = ueye.HIDS(0)  # 0: first available camera;  1-254: The camera with the specified camera ID
        self.sInfo = ueye.SENSORINFO()
        self.cInfo = ueye.CAMINFO()
        self.pcImageMemory = ueye.c_mem_p()
        self.MemID = ueye.int()

        # Starts the driver and establishes the connection to the camera
        nRet = ueye.is_InitCamera(self.hCam, None)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_InitCamera ERROR")

        # Reads out the data hard-coded in the non-volatile camera memory and writes it to the data structure that cInfo points to
        nRet = ueye.is_GetCameraInfo(self.hCam, self.cInfo)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_GetCameraInfo ERROR")

        # You can query additional information about the sensor type used in the camera
        nRet = ueye.is_GetSensorInfo(self.hCam, self.sInfo)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_GetSensorInfo ERROR")

        print("Camera model:\t\t", self.sInfo.strSensorName.decode('utf-8'))
        print("Camera serial no.:\t", self.cInfo.SerNo.decode('utf-8'))

        self.dev_list = [(0, self.sInfo.strSensorName.decode('utf-8'), self.cInfo.SerNo.decode('utf-8'))]

        """
        Pixel Clocks for UC3240 camera:
        [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 
         34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 
         70, 72, 74, 76, 78, 80, 82, 84, 86]
        """
        self.sample_mode = 'off'        # 'off', 'live', 'still'
        self.uses_messages = True
        # (fps, etms, navg)
        self.exp_param = ((15., 20., 1),
                          (15., 28., 1),
                          (15., 40., 1),
                          (15., 57., 1),
                          (12., 80., 1),
                          (10., 100., 1),
                          (7., 140., 1),
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


        nRet = ueye.is_ResetToDefault(self.hCam)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_ResetToDefault ERROR")


        #self.api.setup_memory(FRAME_WIDTH, FRAME_HEIGHT, FRAME_BITS_PER_PIXEL)
        nRet = ueye.is_AllocImageMem(self.hCam, FRAME_WIDTH, FRAME_HEIGHT, FRAME_BITS_PER_PIXEL, self.pcImageMemory, self.MemID)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_AllocImageMem ERROR")

        nRet = ueye.is_SetImageMem(self.hCam, self.pcImageMemory, self.MemID)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_SetImageMem ERROR")

        nRet = ueye.is_SetColorMode(self.hCam, COLOR_MODE)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_SetColorMode ERROR")


        pc = uu.set_pixel_clock(self.hCam, UC480_PIXEL_CLOCK_TO_USE)

        #self.api.SetBinning(H.IS_BINNING_2X_HORIZONTAL | H.IS_BINNING_2X_VERTICAL)

        #ueye.is_SetBinning(self.hCam, ueye.IS_BINNING_2X_HORIZONTAL | ueye.IS_BINNING_2X_VERTICAL)

        uu.set_flash_active_high(self.hCam)


        #ft, ftmin, ftmax, ftint = uu.get_frame_time_settings(self.hCam)
        #print('FT:', ft, ftmin, ftmax, ftint)
        #print('FR:', 1./ft, 1./ftmin, 1./ftmax, 1./ftint)

        #et, etmin, etmax, etinc = uu.get_exposure_settings(self.hCam)
        #print('ET: ', et, etmin, etmax, etinc)
        
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

        """
        Setup a timer and connect it.  However, timer is only used in "still" mode.
        """

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.__tick_callback)

        nRet = uu.is_EnableMessage(self.hCam, ueye.IS_FRAME, win_id)    # Corrected function in utils.
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_EnableMessage ERROR")



    def start_sampling(self, uf_callback):
        self.uf_callback = uf_callback
        self.sample_mode = 'live'

        nRet = ueye.is_CaptureVideo(self.hCam, ueye.IS_DONT_WAIT)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_CaptureVideo ERROR")

    def __tick_callback(self):
        nRet = ueye.is_FreezeVideo(self.hCam, ueye.IS_DONT_WAIT)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_FreezeVideo ERROR")


    def set_exposure(self, exp_ndx, ifi_ndx):

        if self.sample_mode != 'off':
            #self.api.StopLiveVideo(wait=H.IS_FORCE_VIDEO_STOP)
            nRet = ueye.is_StopLiveVideo(self.hCam, ueye.IS_DONT_WAIT)
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_StopLiveVideo ERROR")

        if self.sample_mode == 'still':
            self.timer.stop()

        self.current_exposure_index = exp_ndx
        self.current_ifi_index = ifi_ndx
        ep = self.exp_param[exp_ndx]

        # with software trigger, synchronizes the exposure to begin after calls to
        # FreezeVideo and CaptureVideo

        if ifi_ndx == 0:

            fps_c, new_fps_c = DOUBLE(ep[0]), DOUBLE(0)
            nRet = ueye.is_SetFrameRate(self.hCam, fps_c, new_fps_c)
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_SetFrameRate ERROR")

            self.actual_frame_rate = new_fps_c.value

            nRet = ueye.is_SetExternalTrigger(self.hCam, ueye.IS_SET_TRIGGER_OFF)
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_SetExternalTrigger ERROR")

            cParam = DOUBLE(ep[1])
            nRet = ueye.is_Exposure(self.hCam, ueye.IS_EXPOSURE_CMD_SET_EXPOSURE, cParam, UINT(sizeof(DOUBLE)))
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_Exposure ERROR")

            cam_exp = cParam.value  # Set command returns actual
            self.actual_exposure_time_ms = cam_exp * ep[2]


            if self.sample_mode != 'off':
                self.sample_mode = 'live'
                nRet = ueye.is_CaptureVideo(self.hCam, ueye.IS_DONT_WAIT)
                if nRet != ueye.IS_SUCCESS:
                    raise SystemError("is_CaptureVideo ERROR")

        else:
            nRet = ueye.is_SetExternalTrigger(self.hCam, ueye.IS_SET_TRIGGER_SOFTWARE)
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_SetExternalTrigger ERROR")
            self.actual_frame_rate = 1000./self.ifi_settings[ifi_ndx]

            #cam_exp = self.api.set_exposure(ep[1])

            cParam = DOUBLE(ep[1])
            nRet = ueye.is_Exposure(self.hCam, ueye.IS_EXPOSURE_CMD_SET_EXPOSURE, cParam, UINT(sizeof(DOUBLE)))
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_Exposure ERROR")

            cam_exp = cParam.value
            self.actual_exposure_time_ms = cam_exp * ep[2]
            self.sample_mode = 'still'
            nRet = ueye.is_FreezeVideo(self.hCam, ueye.IS_DONT_WAIT)
            if nRet != ueye.IS_SUCCESS:
                raise SystemError("is_FreezeVideo ERROR")

            self.timer.start(self.ifi_settings[ifi_ndx])

        self.frame_ptr = 0

        #print('returned exposure time:', cam_exp)
        #et, etmin, etmax, etinc = uu.get_exposure_settings(self.hCam)
        #print('ET: ', et, etmin, etmax, etinc)

    def led_state(self, state):
        """

        Parameters
        ----------
        state : str
            set the LED to 'ON', 'OFF', or 'AUTO'.  Auto means controlled by the exposure.


        """
        if state == 'ON':
            uu.set_flash_output_state(self.hCam, True)
        elif state == 'OFF':
            uu.set_flash_output_state(self.hCam, False)
        elif state == 'AUTO':
            """
            Note that if software trigger is enabled (non-zoro IFI) then must turn the trigger off change to
            active high then back on.  This might cause a problem if a timer tick occurs concurrently.
            """
            if self.current_ifi_index != 0:
                nRet = ueye.is_SetExternalTrigger(self.hCam, ueye.IS_SET_TRIGGER_OFF)
                if nRet != ueye.IS_SUCCESS:
                    raise SystemError("is_SetExternalTrigger ERROR")

            uu.set_flash_active_high(self.hCam)
            if self.current_ifi_index != 0:
                nRet = ueye.is_SetExternalTrigger(self.hCam, ueye.IS_SET_TRIGGER_SOFTWARE)
                if nRet != ueye.IS_SUCCESS:
                    raise SystemError("is_SetExternalTrigger ERROR")

        else:
            raise SystemError('Invalid state parameter')

    def msg_event(self, msg):
        if msg.message == UC480_MESSAGE:

            if self.sample_mode == 'off':   # Messages are sent during shutdown when resources might be freeing up.
                return True, 0

            if (msg.wParam == ueye.IS_FRAME):
                # print('msg = %x, %x, %x' % (msg.message, msg.lParam, msg.wParam))
                self._update_image()
                return True, 0

        return False, 0

    def stop_sampling(self):
        #self.api.StopLiveVideo(wait=H.IS_FORCE_VIDEO_STOP)  # both live and still
        nRet = ueye.is_StopLiveVideo(self.hCam, ueye.IS_FORCE_VIDEO_STOP)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_StopLiveVideo ERROR")

        uu.set_flash_output_state(self.hCam, False)
        if self.sample_mode == 'still':
            self.timer.stop()
        self.sample_mode = 'off'

    def release(self):
        nRet = uu.is_EnableMessage(self.hCam, ueye.IS_FRAME, 0)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_Enable(disable)Message ERROR")

        nRet = ueye.is_FreeImageMem(self.hCam, self.pcImageMemory, self.MemID)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_FreeImageMem ERROR")

        nRet = ueye.is_ExitCamera(self.hCam)
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_ExitCamera ERROR")

    def _update_image(self):
        """
        Called when a frame is ready to read.  If this is still mode then timer will trigger the next
        acquisition.  In this case, turn off the flash o/p, timer service routine will turn it on again.

        Returns
        -------

        """


        dest = self.frame[self.frame_ptr]

        nRet = ueye.is_CopyImageMem(self.hCam, self.pcImageMemory, self.MemID, dest.ctypes.data_as(c_char_p))
        if nRet != ueye.IS_SUCCESS:
            raise SystemError("is_CopyImageMem ERROR")

        self.frame_ptr += 1
        max_frame = self.exp_param[self.current_exposure_index][2]
        if self.frame_ptr >= max_frame:
            self.frame_ptr = 0
            if max_frame == 1:
                f = self.frame[0, :, :] # no need to sum and clip if only one (most often)
            else:
                f = np.clip(np.sum(self.frame[0:max_frame, :, :], axis=0, dtype=np.int16), 0, self.pixel_maxval)
            #self.uf_callback(f[::2,128:-128:2])
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

    def set_exposure(self, exp_ndx, ifi_ndx):
        self.current_exposure_index = exp_ndx
        self.current_ifi_index = ifi_ndx
        if self.timer is not None:
            if ifi_ndx == 0:
                self.timer.setInterval(self.exposure_settings[exp_ndx])
            else:
                self.timer.setInterval(self.ifi_settings[ifi_ndx])
            #self.timer.setInterval(self.exposure_settings[exp_ndx])
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

    def set_exposure(self, exp_ndx, ifi_ndx):
        self.current_exposure_index = exp_ndx
        self.current_ifi_index = ifi_ndx
        if ifi_ndx == 0:
            interval = self.exposure_settings[exp_ndx]
        else:
            interval = self.ifi_settings[ifi_ndx]

        self.api.set(cv2.CAP_PROP_FPS, 1000. / interval)
        if self.timer is not None:
            self.timer.setInterval(interval)

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
