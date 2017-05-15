"""
Classes and functions to support the two screens (live and capture) and associated graphics and mouse events.

M. Palmer, June 2016
"""
from PyQt5 import QtCore, QtWidgets, QtGui, QtMultimedia
from PyQt5.QtCore import Qt
import numpy as np
from matplotlib.path import Path

LIVE_SCREEN_TAG = 'liveScreen'
LIVE_SCREEN_STYLE_LIVE = '{ border: 2px solid green; }'
LIVE_SCREEN_STYLE_STILL = '{ border: 2px solid red; }'
CAP_SCREEN_TAG = 'capScreen'
CAP_SCREEN_STYLE_STILL0 = '{ border: 1px solid blue; }'
CAP_SCREEN_STYLE_STILL = '{ border: 1px solid red; }'
CAP_SCREEN_STYLE_LIVE = '{ border: 1px solid green; }'

MOUSE_POS_COLOR = Qt.yellow
MOUSE_POS_FONT = 'Courier'
MOUSE_POS_FONTSIZE = 14
MOUSE_POS_X = 1150
MOUSE_POS_Y = 20

ROI_HIGHLIGHT_COLOR = Qt.red
ROI_COLOR = Qt.yellow
ARROW_COLOR = Qt.blue
ARROW_ACTIVATED_COLOR = Qt.green
ARROW_HEAD_ANGLE = 20 * np.pi/180.
ARROW_HEAD_LENGTH = 15.
ARROW_SHAFT_WIDTH = 3

CAP_TITLE_COLOR_LIVE = Qt.green
CAP_TITLE_COLOR_STILL = Qt.red
CAP_TITLE_FONT = 'Arial'
CAP_TITLE_FONTSIZE = 12
CAP_TITLE_X = 2
CAP_TITLE_Y = 15

LIVE_TITLE_COLOR_LIVE = Qt.green
LIVE_TITLE_COLOR_STILL = Qt.red
LIVE_TITLE_X = 4
LIVE_TITLE_Y = 20
LIVE_TITLE_FONT = "Ariel"
LIVE_TITLE_FONTSIZE = 14

class Roi(QtGui.QPolygon):
    """
    ROI class.  Basically a polygon with a few added characteristics
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.visible = True
        self.color = ROI_COLOR
        self.activated = False  # set to enable control point views

    def translated(self, *args):
        """
        Needed for full ROI movement - translated method returns a QPolygon
        """
        poly = super().translated(*args)
        poly.visible = self.visible
        poly.color = self.color
        poly.activated = self.activated
        return poly


class Arrow(QtCore.QLine):
    """
    New graphical class built from a line and a 3-point polygon.  P1 is the
    head end of the arrow.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.visible = True
        self.activated = False

        self.head = QtGui.QPolygon(3)

        theta = np.arctan2(self.dy(), self.dx())
        ha1 = theta + ARROW_HEAD_ANGLE
        ha2 = theta - ARROW_HEAD_ANGLE

        self.head.setPoint(1, self.p1())
        self.head.setPoint(0, self.x1() + ARROW_HEAD_LENGTH * np.cos(ha1),
                           self.y1() + ARROW_HEAD_LENGTH * np.sin(ha1))
        self.head.setPoint(2, self.x1() + ARROW_HEAD_LENGTH * np.cos(ha2),
                           self.y1() + ARROW_HEAD_LENGTH * np.sin(ha2))

    def __del__(self):
        """
        Not really sure if this is operating correctly
        """
        self.head.clear()


def poly2mask(qpoly, shape):
    """
    Convert polygon to binary mask

    ref: http://stackoverflow.com/questions/3654289/scipy-create-2d-polygon-mask

    Parameters
    ----------
    poly : QPolygon

    shape : (x, y)
        extent
    """

    ny, nx = shape

    poly_verts = [(p.x(), p.y()) for p in qpoly]

    # Create vertex coordinates for each grid cell...
    # (<0,0> is at the top left of the grid in this system)
    x, y = np.meshgrid(np.arange(nx), np.arange(ny))
    x, y = x.flatten(), y.flatten()

    points = np.vstack((x, y)).T

    path = Path(poly_verts)

    grid = path.contains_points(points)
    grid = grid.reshape((ny, nx))

    return grid


class CapScreen(QtWidgets.QLabel):
    """
    A class for manaing the capture screen/pallette.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cap_title = 'No Stills'
        self.cap_loaded = False
        self.cap_title_color = Qt.blue

        self.setObjectName(CAP_SCREEN_TAG)
        self._set_frame(CAP_SCREEN_STYLE_STILL0)

    def _set_frame(self, style):
        """
        Helper function for quick frame changes
        """

        tag = self.objectName()
        self.setStyleSheet('#' + tag + style)

    def format_for_live(self):
        """
        Set the frame border and text color for this screen to indicate "live" image
        Returns
        -------
        none
        """
        self._set_frame(CAP_SCREEN_STYLE_LIVE)
        self.cap_title_color = CAP_TITLE_COLOR_LIVE

    def format_for_cap(self):
        """
        Set the frame border and text color for this screen to indicate captured image
        Returns
        -------
        none
        """
        self._set_frame(CAP_SCREEN_STYLE_STILL)
        self.cap_title_color = CAP_TITLE_COLOR_STILL

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QtGui.QPainter()
        painter.begin(self)

        painter.setPen(self.cap_title_color)
        painter.setFont(QtGui.QFont(CAP_TITLE_FONT, CAP_TITLE_FONTSIZE))
        painter.drawText(CAP_TITLE_X, CAP_TITLE_Y, self.cap_title)

        painter.end()

    def contextMenuEvent(self, event):
        """
        A blank. Not yet implemented.  The idea is to be able to save the image (save as) in other formats.
        Parameters
        ----------
        event

        Returns
        -------

        """
        global image_dir

        if not self.cap_loaded:
            return

        return  # un-finished save-as feature is blocked.

        menu = QtWidgets.QMenu(self)
        save_as_action = menu.addAction("Save As...")
        action = menu.exec_(self.mapToGlobal(event.pos()))
        if action == save_as_action:
            dlg = QtWidgets.QFileDialog()
            dlg.setFileMode(QtWidgets.QFileDialog.AnyFile)
            dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
            dlg.setNameFilters(["Scaled Image (*.tif, *.png,*.jpg)", "Raw Image (*.tif)"])
            if dlg.exec_():
                fn = dlg.selectedFiles()
                filter = dlg.selectedNameFilter()
                print('fn:', fn)
                print('filter: ', filter)


class LiveScreen(QtWidgets.QLabel):
    """
    A class for managing the main screen.

    ROI State:
            0 - nothing happening
            1 - one or more points defined, building new ROI
            2 - moving a control point or the entire ROI (index set to -1)
            3 - dragging to place an arrow

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.roi_button = None
        self.setMouseTracking(True)
        self.last_mouse_pos = QtCore.QPoint(0, 0)
        self.rect0 = QtCore.QRect(0, 0, 10, 10)
        self.rect0.adjust(-5, -5, -5, -5)

        self.roi_list = []

        self.roi_build = Roi()
        self.roi_build.activated = True
        self.roi_build.color = Qt.green
        self.roi_state = 0
        self.roi_move_coords = []
        self.last_press_pos = None
        self.arrow_list = []
        self.arrow_build = QtCore.QLine()

        self.live_title = ''
        self.live_title_color = LIVE_TITLE_COLOR_LIVE

        self.setObjectName(LIVE_SCREEN_TAG)
        self._set_frame(LIVE_SCREEN_STYLE_LIVE)

    def _set_frame(self, style):
        """
        Helper function for quick frame changes
        """

        tag = self.objectName()
        self.setStyleSheet('#' + tag + style)

    def connect_roi_button(self, roi_button):
        """
        Method to associate the ROI button on the viewer in order to maintain its enable state.

        Parameters
        ----------
        roi_button

        Returns
        -------

        """
        self.roi_button = roi_button

    def format_for_live(self):
        """
        Set the frame border and text color for this screen to indicate "live" image
        Returns
        -------
        none
        """
        self._set_frame(LIVE_SCREEN_STYLE_LIVE)
        self.live_title_color = LIVE_TITLE_COLOR_LIVE

    def format_for_cap(self):
        """
        Set the frame border and text color for this screen to indicate captured image
        Returns
        -------
        none
        """
        self._set_frame(LIVE_SCREEN_STYLE_STILL)
        self.live_title_color = LIVE_TITLE_COLOR_STILL


    def roi_mask(self):
        """
        Return the mask corresponding to the active roi.  If only one ROI
        is defined, treat is as if it were active.  If no ROIs or if more than
        one and nothing active, return None.
        """
        if len(self.roi_list) == 1:
            return poly2mask(self.roi_list[0], (self.pixmap().height(), self.pixmap().width()))
        for r in self.roi_list:
            if r.activated:
                return poly2mask(r, (self.pixmap().height(), self.pixmap().width()))

        return None

    def delete_features(self):
        """
        Delete all ROIs and arrows
        :return: 
        """
        self.roi_list = []
        self.arrow_list = []
        self.repaint(self.rect())


    def delete_activated(self):
        """
        Delete first ROI or Arrow encountered:  Can only have one activated
        feature.  Repaint screen when feature's removed from list.  If nothing
        activated, don't do anything.
        """
        for ri, r in enumerate(self.roi_list):
            if r.activated:
                self.roi_list.pop(ri)
                if len(self.roi_list) == 0:
                    self.roi_button.setEnabled(False)
                self.repaint(self.rect())  # maybe not optimal to repaint entire widget
                return

        for ai, a in enumerate(self.arrow_list):
            if a.activated:
                self.arrow_list.pop(ai)
                self.repaint(self.rect())  # maybe not optimal to replaint entire widget

    def pos_in_pixmap(self, pos):
        """
        Correct for mouse position (widget) to pixmap coordinate.

        • The pixmap seems to be centered in the widget.  As it's resized, it stays at the center.
        • The pixmap().rect() is always 0,0,xw,yw which comes from the pixmap.  The rect property doesn't
          get updated to show where it was or should be rendered.
	    • The geometry is the rectangle defining the paintable portion of the widget (although maybe some
	      confusion with frameGeometry).  It includes the border.  For example, in a label widget that contains
	      just the pixmap and a border (from a style), the geometry is (0,0,1284,1028) when the pixmap().rect()
	      is (0,0,1280,1024) and the border is 2 pixels wide.
	    • Algorithm: so I think that the algorithm to convert points referenced to the widget (e.g. mouse positions)
	      to points referenced to the pixmap is to subtract the offset between rectangle centers.

        Parameters
        ----------
        pos : QPoint
            position to convert.  This is in (event) units relative to the widget.
        Returns
        -------
        ppos : QPoint
            position within the pixmap

        """
        return pos - (self.rect().center() - self.pixmap().rect().center())

    def pos_in_widget(self, pos):
        """
        Correct a position relative to the pixmal to that of the widget. Inverse of pos_in_pixmap

        Parameters
        ----------
        pos : (QPoint)
            a position in the pixmap.
        Returns
        -------
        npos : QPoint
            a position relative to the widget.

        """

        return pos + (self.rect().center() - self.pixmap().rect().center())

    def mouseMoveEvent(self, event):
        """
        Handle mouse movements in LiveScreen.

            ROI State:
            0 - nothing happening
            1 - one or more points defined, building new ROI
            2 - moving a control point or the entire ROI (index set to -1)
            3 - dragging to place an arrow

        Parameters
        ----------
        event

        Returns
        -------

        """

        ppos = self.pos_in_pixmap(event.pos())
        if not self.pixmap().rect().contains(ppos):
            return

        self.last_mouse_pos = ppos

        if self.roi_state == 1: # Building ROI
            self.update()
            return

        if self.roi_state == 2: # moving control point or ROI
            ri, pi, pos0, roi0 = self.roi_move_coords
            if pi < 0:
                self.roi_list[ri].clear()
                self.roi_list[ri] = roi0.translated(ppos - pos0)
                self.roi_list[ri].activated = True
            else:
                self.roi_list[ri].setPoint(pi, ppos)
            self.update()
            return

        elif self.roi_state == 3: # dragging to define an arrow
            self.arrow_build.setP2(ppos)
            self.update()
            return

        """
        Only State 0 beyond here.We are not already building an arrow so are we dragging?
        """
        if event.buttons() & Qt.LeftButton:
            self.arrow_build.setP1(self.last_press_pos)
            self.roi_state = 3
            self.update()
            return

        for r in self.roi_list:
            if r.containsPoint(ppos, Qt.OddEvenFill):
                r.color = ROI_HIGHLIGHT_COLOR
            else:
                r.color = ROI_COLOR

        self.update()
        # self.repaint(self.rect()) # maybe not optimal to replaint entire widget

    def mousePressEvent(self, event):
        """
        Handle the single mouse press event.  Note that a single press preceeds double click events.

        Parameters
        ----------
        event

        Returns
        -------

            ROI State:
            0 - nothing happening
            1 - one or more points defined, building new ROI
            2 - moving a control point or the entire ROI (index set to -1)
            3 - dragging to place an arrow
        """
        if event.button() != Qt.LeftButton:
            return

        ppos = self.pos_in_pixmap(event.pos())
        if not self.pixmap().rect().contains(ppos):     # Have to be inside the pixmap.
            return

        self.last_press_pos = ppos
        if self.roi_state == 1:  # we are currently building an ROI, add this point to it.
            self.roi_build.append(ppos)
            self.update()
            return
        if self.roi_state == 0:  # quiescent state
            for r in self.roi_list:
                r.activated = r.containsPoint(ppos, Qt.OddEvenFill)  # Set or reset the ROI activation state
            for a in self.arrow_list:
                a.activated = a.head.containsPoint(ppos, Qt.OddEvenFill)  # set or reset the Arrow activation state

            for ri, r in enumerate(self.roi_list):  # on ROI's or control points?
                if r.activated:
                    for pi, p in enumerate(r):
                        if self.rect0.translated(p).contains(ppos):
                            self.roi_state = 2
                            self.roi_move_coords = [ri, pi, ppos, None]
                            self.update()
                            return

                if r.containsPoint(ppos, Qt.OddEvenFill):  # on the ROI?
                    self.roi_state = 2
                    self.roi_move_coords = [ri, -1, ppos, Roi(r)]  # move entire ROI
                    r.activated = True
                    self.update()
                    return

        self.update()
        return

    def mouseReleaseEvent(self, event):
        """
        Mouse button release event handling.

        Remember that the release event occurs after every click.

        The purpose of subclassing this is to terminate drag operations.  Also, check the ROI activation state to
        set the ROI enable correctly.

        Parameters
        ----------
        event

        Returns
        -------

        """
        if event.button() != Qt.LeftButton:
            return

        ppos = self.pos_in_pixmap(event.pos())
        if not self.pixmap().rect().contains(ppos):
            return

        if self.roi_state == 3:  # draggin for arrow building.
            self.roi_state = 0
            self.arrow_list.append(Arrow(self.arrow_build))

        elif self.roi_state == 2: # dragging for moving control points or the entire ROI
            self.roi_state = 0

        if len(self.roi_list) == 1:
            self.roi_button.setEnabled(True)
        elif len(self.roi_list) > 1:
            rois_active = False
            for r in self.roi_list:
                if r.activated:
                    rois_active = True
            self.roi_button.setEnabled(rois_active)

        self.update()

    def mouseDoubleClickEvent(self, event):
        """
        Handle the double click event.

        Note that a mousePressEvent always preceeds a mouseDoubleClick event.
        If state 0, quiescent, then this double click is to initiate building an ROI.  Add the point, change the
        state control variable and carry on.
        If state 1, then we have been building an ROI so time to stop.  First make sure there's more than 2 points
        (if not just change state and return).  Next move the temp ROI to the ROI list, change the state back to 0
        and return. Finally, if there's exactly one ROI now defined, activate the button.
        """

        if event.button() != Qt.LeftButton:
            return

        ppos = self.pos_in_pixmap(event.pos())
        if not self.pixmap().rect().contains(ppos):
            return

        if self.roi_state == 0:  # quiescent state, start building the ROI.
            self.roi_build.append(ppos)
            self.roi_state = 1
        elif self.roi_state == 1: # we are building so now terminate the build, move it to the list.
            self.roi_state = 0
            if len(self.roi_build) > 2:
                self.roi_list.append(Roi(self.roi_build))  # make deep copy
            self.roi_build.clear()
        else:
            raise SystemExit('unknown state')


        self.update()

    def paintEvent(self, event):
        """
        Locally modified paint event to add in the graphics drawing and titling.

        Parameters
        ----------
        event

        Returns
        -------

        """

        super().paintEvent(event)

        painter = QtGui.QPainter()
        painter.begin(self)

        # drawing offsets:
        do_x = self.rect().center().x() - self.pixmap().rect().center().x()
        do_y = self.rect().center().y() - self.pixmap().rect().center().y()

        painter.setPen(MOUSE_POS_COLOR)
        painter.setFont(QtGui.QFont(MOUSE_POS_FONT, MOUSE_POS_FONTSIZE))
        s = '(%4.4d,%4.4d)' % (self.last_mouse_pos.x(), self.last_mouse_pos.y())
        painter.drawText(MOUSE_POS_X + do_x, MOUSE_POS_Y + do_y, s)

        painter.setPen(self.live_title_color)
        painter.setFont(QtGui.QFont(LIVE_TITLE_FONT, LIVE_TITLE_FONTSIZE))
        painter.drawText(LIVE_TITLE_X + do_x, LIVE_TITLE_Y + do_y, self.live_title)

        painter.setBrush(Qt.NoBrush)  # Open polygons
        for r in self.roi_list:
            if (r.visible):
                painter.setPen(r.color)
                painter.drawPolygon(r.translated(do_x, do_y))
                if r.activated:
                    for p in r:
                        painter.drawRect(self.rect0.translated(p).translated(do_x, do_y))

        painter.setPen(self.roi_build.color)
        painter.drawPolyline(self.roi_build.translated(do_x, do_y))
        for p in self.roi_build:
            painter.drawRect(self.rect0.translated(p).translated(do_x, do_y))

        """
        Draw arrows.  List then under construction:
        """

        nbrush = QtGui.QBrush(ARROW_COLOR, Qt.SolidPattern)
        npen = QtGui.QPen(ARROW_COLOR, ARROW_SHAFT_WIDTH)
        abrush = QtGui.QBrush(ARROW_ACTIVATED_COLOR, Qt.SolidPattern)
        apen = QtGui.QPen(ARROW_ACTIVATED_COLOR, ARROW_SHAFT_WIDTH)
        painter.setBrush(nbrush)
        painter.setPen(npen)
        for a in self.arrow_list:
            if a.activated:
                painter.setBrush(abrush)
                painter.setPen(apen)
            else:
                painter.setBrush(nbrush)
                painter.setPen(npen)

            painter.drawLine(a.translated(do_x, do_y))
            painter.drawPolygon(a.head.translated(do_x, do_y))

        if self.roi_state == 3:
            painter.drawLine(self.arrow_build.translated(do_x, do_y))

        painter.end()
