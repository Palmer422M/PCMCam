"""
File originated as ueye.py from the pydcu package at probably from https://github.com/wmpauli/pydcu

Consists of wrappers for the Thorlabs SDK routines.

Not a complete interface.  Not all routines tested.

M. Palmer, 4/1/2016

Mod History:
 - 4/27/2017: Removed the subclassing of the HCAM/DWORD object.  Python 3.6 doesn't seem to allow subclassing ctypes
    classes which might be a bug (http://bugs.python.org/issue29270), but it was easy to get around - no need to subclass.

"""

from ctypes import byref, c_char_p, pointer, sizeof
from ctypes.wintypes import HWND, INT, UINT, DOUBLE
import ctypes, ctypes.util
import numpy as np

import uc480_H as H

HCAM = ctypes.c_uint32  # this is defined as DWORD in uc480.py which is in turn defined as uint32

class UC480_CAMERA_INFO(ctypes.Structure):
    _fields_ = [("CameraID", ctypes.c_uint32),
                ("DeviceID", ctypes.c_uint32),
                ("SensorID", ctypes.c_uint32),
                ("InUse", ctypes.c_uint32),
                ("SerNo", ctypes.c_ubyte * 16),
                ("Model", ctypes.c_ubyte * 16),
                ("Status", ctypes.c_uint32),
                ("Reserved", ctypes.c_uint32 * 15)]

class UC480_CAMERA_LIST(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_ulong),
                ("uci", UC480_CAMERA_INFO)]
                

libuc480 = None


def CALL(name, *args):
    """
    Calls uc480 function "name" and arguments "args".
    """
    funcname = 'is_' + name
    func = getattr(libuc480, funcname)
    new_args = []
    for a in args:        
        if isinstance (a, str):
            #print(name, 'argument',a, 'is unicode')
            new_args.append (str (a))
        else:
            new_args.append (a)
    return func(*new_args) 

def device_lookup():
    """
    Check for existence of library first.  If present, load it.
    returns list of devices or none.
    list at present is max of one long.  List members are:
    (cameraID, Model, SN)
    """    
    global libuc480
    lib = ctypes.util.find_library(H.DRIVER_DLL_NAME)
    if lib is None:
        return None
    libuc480 = ctypes.windll.LoadLibrary(lib)
    
    device_list = []
    
    nc = INT(0)
    r = CALL("GetNumberOfCameras", byref(nc))
    if r is not H.IS_SUCCESS:
        raise Exception("Error %d in GetNumberOfCameras"%r)
    
    
    if nc.value < 1:
        return device_list     # return empty list
    
    cam_list = UC480_CAMERA_LIST(1, ())
    
    r = CALL("GetCameraList", byref(cam_list))
    if r is not H.IS_SUCCESS:
        raise Exception("Error %d in GetCameraList"%r)
    
    device_list.append((cam_list.uci.CameraID, 
                        "".join(map(chr, cam_list.uci.Model)).strip(),
                        "".join(map(chr, cam_list.uci.SerNo)).strip()))
    
    return device_list


class RawCamera(object):
    """
    This is the class-based i/f to the uEye driver.  It's currently (2016) a mix of wrappers
    code.  As it evolves, try to separate into raw and derived (camera).
    """
    def __init__(self, hCam=0):
        #super().__init__(hCam) # crashing Python 3.6
        self.hCam = HCAM(hCam)

        r = CALL('InitCamera', byref(self.hCam), self.hCam)
        if r is not H.IS_SUCCESS:
            raise Exception("Error %d"%r)
        return None
        
    def CheckForSuccessError(self, return_value):
        if return_value is not H.IS_SUCCESS:
            self.GetError()
            raise Exception(self.error_message.value)
        return H.IS_SUCCESS

    def CheckForNoSuccessError(self, return_value):
        if return_value is H.IS_NO_SUCCESS:
            self.GetError()
            raise Exception(self.error_message.value)
        return return_value

    def EnableMessage(self, which, hWnd):
        """
        Enable Windows messages for certain functions
        """
        rc = CALL('EnableMessage', self.hCam, INT(which), INT(hWnd))
        self.CheckForSuccessError(rc)

    def DisableMessage(self, which):
        """
        Enable Windows messages for certain functions
        """
        rc = CALL('EnableMessage', self.hCam, INT(which), None)
        self.CheckForSuccessError(rc)
        
        
    def AllocImageMem(self, width, height, bitpixel, pcImgMem, memid):
        """
        AllocImageMem() allocates image memory for an image with width,
        width and height, height and colour depth bitspixel. Memory size
        is at least:

        size = [width * ((bitspixel + 1) / 8) + adjust] * height
        adjust see below

        Line increments are calculated with:

        line     = width * [(bitspixel + 1) / 8]
        lineinc = line + adjust.
        adjust  = 0 when line without rest is divisible by 4
        adjust     = 4 - rest(line / 4) 
                when line without rest is not divisible by 4


        The line increment can be read with the GetImgMemPitch() func-
        tion. The start address in the image memory is returned with 
        ppcImgMem. pid contains an identification number of the alloc-
        ated memory. A newly activated memory location is not directly 
        activated. In other words, images are not directly digitized to
        this new memory location. Before this can happen, the new memory
        location has to be activated with SetImageMem(). After 
        SetImageMem() an SetImageSize() must follow so that the image 
        conditions can be transferred to the newly activated memory 
        location. The returned pointer has to be saved and may be 
        reused, as it is required for all further ImageMem functions! 
        The freeing of the memory is achieved with FreeImageMem(). In 
        the DirectDraw modes, the allocation of an image memory is not 
        required!
        """
        r =  CALL('AllocImageMem',self.hCam,
            INT(width),
            INT(height),
            INT(bitpixel),
            byref(pcImgMem),
            byref(memid))
        return self.CheckForSuccessError(r)

    def SetImageMem(self, pcImgMem, memid):
        """
        SetImageMem() sets the allocated image memory to active memory.
        Only an active image memory can receive image data. After 
        calling SetImageMem() function SetImageSize() must follow to set
        the image size of the active memory. A pointer from function
        AllocImgMem() has to be given to parameter pcImgMem.
        """
        r = CALL("SetImageMem", self.hCam, pcImgMem, memid)
        return self.CheckForSuccessError(r)
        

    def SetImageSize(self, x, y):#non-zero ret
        """
        Obsolete
        Sets the image size.

        If x is configure to:
        IS.GET_IMAGE_SIZE_X     Retrieval of current width
        IS.GET_IMAGE_SIZE_X_MIN Smallest value for the AOI width
        IS.GET_IMAGE_SIZE_X_MAX Largest value for the AOI width
        IS.GET_IMAGE_SIZE_X_INC Increment for the AOI width
        IS.GET_IMAGE_SIZE_Y     Retrieval of current height
        IS.GET_IMAGE_SIZE_Y_MIN Smallest value for the AOI height
        IS.GET_IMAGE_SIZE_Y_MAX Largest value for the AOI height
        IS.GET_IMAGE_SIZE_Y_INC Increment for the AOI height
        y is ignored and the specified size is returned.
        """
        r = CALL("SetImageSize", self.hCam, INT(x), INT(y))
        if x & 0x8000 == 0x8000:
            return self.CheckForNoSuccessError(r)
        return self.CheckForSuccessError(r)
        
    def FreeImageMem (self, pcImgMem, memid):
        """
        FreeImageMem() deallocates previously allocated image memory.i
        For pcImgMem one of the pointers from AllocImgMem() has to be 
        used. All other pointers lead to an error message! The repeated
        handing over of the same pointers also leads to an error message
        """
        r = CALL("FreeImageMem", self.hCam, pcImgMem, memid)
        return self.CheckForSuccessError(r)

    def FreezeVideo(self, wait=H.IS_WAIT):
        CALL("FreezeVideo", self.hCam, INT(wait))
        
    def CopyImageMem(self, pcSource, memid, pcDest):
        """
        CopyImageMem() copies the contents of the image memory, as
        described is pcSource and nID to the area in memory, which 
        pcDest points to.  
        """
        r = CALL("CopyImageMem", self.hCam, pcSource, memid, pcDest)
        
        return self.CheckForSuccessError(r)

    def GetError(self):
        self.error = INT()
        self.error_message = c_char_p()
        return CALL("GetError", self.hCam,
            byref(self.error),
            byref(self.error_message))

    def CaptureVideo(self, wait=H.IS_DONT_WAIT):
        """
        CaptureVideo() digitizes video images in real time and transfers
        the images to the previously allocated image memory. 
        Alternatively if you are using DirectDraw the images can be 
        transferred to the graphics board. The image acquisition (DIB 
        Mode) takes place in the memory which has been set by 
        SetImageMem() and AllocImageMem(). GetImageMem() determines 
        exactly where the start address in memory H.IS_ In case of ring 
        buffering, then image acquisition loops endlessly through all 
        image memeories added to the sequence.

        wait
         H.IS_DONT_WAIT    This function synchronizes the image acquisition                of the V-SYNC, but returns immediately.
        H.IS_WAIT        This function synchronizes the image acquisition
                of the V-SYNC and only then does return (i.e.
                waits until image acquisition begins)
        10<wait<32768    Wait time in 10 ms steps. A maximum of 327.68 
                seconds (this is approx. 5 minutes and 20 
                seconds) can be waited. For 1 < Wait < 10 Wait 
                becomes equal to 10.
        (Exp.: Wait = 100 => wait 1 sec.)
        """
        r = CALL("CaptureVideo", self.hCam, INT(wait))
        return self.CheckForSuccessError(r)
        

    def SetColorMode(self, color_mode):
        r = CALL("SetColorMode", self.hCam, INT(color_mode))
        return self.CheckForNoSuccessError(r)
    
    def StopLiveVideo(self, wait=H.IS_DONT_WAIT):
        """
        The StopLiveVideo() function freezes the image in the VGA card 
        or in the PC's system memory. The function is controlled with 
        the parameter Wait. The function has two modes: Using the first
        mode, the function immediately returns to the calling function 
        and grabs the image in the background. In the second mode the 
        function waits until the image has been completely acquired and
        only then does the function return.
        By the use of H.IS_FORCE_VIDEO_STOP a single frame recording which
        is started with FreezeVideo(H.IS_DONT_WAIT) can be terminated
        immediately.
        """
        r = CALL("StopLiveVideo", self.hCam, INT(wait))
        return self.CheckForSuccessError(r)
        
    def ExitCamera(self):
        r = CALL("ExitCamera", self.hCam)
        return self.CheckForSuccessError(r)

    def PixelClock(self, Command, Param):
        """
        MRP
        """
        LenParam = len(Param)
        cParam = (UINT * LenParam)(*Param)
        #for idx in range(LenParam): cParam[idx] = Param[idx]
        
        r = CALL("PixelClock", self.hCam, UINT(Command), byref(cParam), UINT(LenParam*sizeof(UINT)))
        self.CheckForSuccessError(r)
        
        for idx in range(LenParam): Param[idx] = cParam[idx]
        # doesn't work: Param = [c for c in cParam]
        

    def Exposure(self, Command, Param):
        """
        MRP
        Note - will only work for is_Exposures calls for which Param is double
        """
        LenParam = len(Param)
        cParam = (DOUBLE * LenParam)(*Param)
        r = CALL('Exposure', self.hCam, UINT(Command), byref(cParam), UINT(LenParam*sizeof(DOUBLE)))
        self.CheckForSuccessError(r)
        for idx in range(LenParam): Param[idx] = cParam[idx]
     

    def SetFrameRate(self, fps=30):
        fps_c = ctypes.c_double(fps)
        new_fps_c = ctypes.c_double(0)
        r = CALL('SetFrameRate', self.hCam, fps_c, byref(new_fps_c))
        return new_fps_c.value

    def GetFrameTimeRange(self, fmin, fmax, fint):
        """
        Note - fmin, fmax, fint must be mutable objects.  typically lists
        with one element each.
        """

        dfmin, dfmax, dfint = DOUBLE(0), DOUBLE(0), DOUBLE(0)
        r = CALL('GetFrameTimeRange', self.hCam, byref(dfmin), byref(dfmax), byref(dfint))
        self.CheckForSuccessError(r)
        fmin[0], fmax[0], fint[0] = dfmin.value, dfmax.value, dfint.value


    def EnableEvent(self, event=H.IS_SET_EVENT_FRAME):
        which = ctypes.c_int(event)
        r = CALL('EnableEvent', self.hCam, which)
        self.CheckForSuccessError(r)


class Camera(RawCamera):
    """
    Class for not-so-pure I/F.
    """
    def setup_memory(self, width, height, bitsperpixel):
        """
        Setup internal buffers for acquisition of frames of given size/depth.

        Parameters
        ----------
        width : uint
            frame width
        height : uint
            frame height
        bitsperpixel : uint
            number of bits per pixel - currently 8 or 16.
        """

        self.pcImgMem = c_char_p()
        self.memid = INT()

        self.AllocImageMem(width, height, bitsperpixel, self.pcImgMem, self.memid)
        self.SetImageMem(self.pcImgMem, self.memid)
        self.SetImageSize(width, height)


    def get_frame(self, dest):
        """
        Copy function for single frame

        Parameters
        ----------
        dest : numpy ndarray 
            size should be matched to internal settings
        """
        self.CopyImageMem(self.pcImgMem, self.memid, dest.ctypes.data_as(c_char_p))


    def set_min_pixel_clock(self):
        """ 
        Set pixel clock to minimum realizable. 

        Parameters
        ----------

        Returns
        -------
            actual pixel clock selected.
        """
        Param = [0]
        self.PixelClock(H.IS_PIXELCLOCK_CMD_GET_NUMBER, Param)
        num_pc = Param[0]

        Param = [0] * num_pc        
        self.PixelClock(H.IS_PIXELCLOCK_CMD_GET_LIST, Param)
        
        Param = [Param[0]] # Set to minimum
        self.PixelClock(H.IS_PIXELCLOCK_CMD_SET, Param)

        return Param[0]

    def cleanup(self):
        self.StopLiveVideo(H.IS_FORCE_VIDEO_STOP) # try this
        self.FreeImageMem(self.pcImgMem, self.memid)
        self.ExitCamera()

    def set_exposure(self, exp_ms):
        """ 
        Set exposure time 

        Parameters
        ----------
        exp_ms : float
            exposure time in ms.  If zero, set to maximum of 1/frame-rate.

        Returns
        -------
            actual exposure time in ms
        """
        Param = [exp_ms]
        self.Exposure(H.IS_EXPOSURE_CMD_SET_EXPOSURE, Param)
        return Param[0]

    def get_exposure_settings(self):
        """ 
        Get exposure time, min, max and increment

        Parameters
        ----------

        Returns
        -------
            (et, etmin, etmax, etinc), the current exposure time in ms,
            the minimum settable, the maximum and the increment.
        """
        Param = [0]
        self.Exposure(H.IS_EXPOSURE_CMD_GET_EXPOSURE, Param)
        et =  Param[0]

        Param = [0, 0, 0]
        self.Exposure(H.IS_EXPOSURE_CMD_GET_EXPOSURE_RANGE, Param)
        return et, Param[0], Param[1], Param[2]

    def GetFrameRate(self):
        """
        This returns the set FrameRate in frames per second
        """

        return self.SetFrameRate(fps=H.IS_GET_FRAMERATE)
        
    def get_frame_time_settings(self):
        """
        Get frame time (duration) current and range

        Note the result is valid for the current pixel-clock setting.
        Frame time (duration) is the inverse of frame rate.

        Parameters
        ----------

        Returns
        -------
        (ft, ftmin, ftmax, ftint)

        """

        fr = self.GetFrameRate()
        ft = 1./fr

        ftmin, ftmax, ftint = [0], [0], [0]
        self.GetFrameTimeRange(ftmin, ftmax, ftint)
        return ft, ftmin[0], ftmax[0], ftint[0]


