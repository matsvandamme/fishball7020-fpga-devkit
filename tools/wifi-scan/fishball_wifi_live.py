#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: Fishball7020 - live Wi-Fi band viewer
# Author: Matthieu
# Description: Live 2.4/5 GHz Wi-Fi viewer for the Fishball7020
# GNU Radio version: 3.10.7.0

from packaging.version import Version as StrictVersion
from PyQt5 import Qt
from gnuradio import qtgui
from PyQt5.QtCore import QObject, pyqtSlot
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import iio
from gnuradio.qtgui import Range, RangeWidget
from PyQt5 import QtCore
import sip



class fishball_wifi_live(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "Fishball7020 - live Wi-Fi band viewer", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("Fishball7020 - live Wi-Fi band viewer")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("GNU Radio", "fishball_wifi_live")

        try:
            if StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
                self.restoreGeometry(self.settings.value("geometry").toByteArray())
            else:
                self.restoreGeometry(self.settings.value("geometry"))
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)

        ##################################################
        # Variables
        ##################################################
        self.uri = uri = 'ip:fishball.local'
        self.samp_rate = samp_rate = 61440000
        self.nfft = nfft = 4096
        self.lo_offset = lo_offset = -15000000
        self.gain = gain = 55
        self.chan = chan = 5320000000

        ##################################################
        # Blocks
        ##################################################

        self._gain_range = Range(0, 62, 1, 55, 200)
        self._gain_win = RangeWidget(self._gain_range, self.set_gain, "RX gain (dB)   -   max is 71 below 4 GHz, 62 above", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._gain_win, 1, 0, 1, 1)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        # Create the options list
        self._chan_options = [2412000000, 2437000000, 2462000000, 5180000000, 5200000000, 5220000000, 5240000000, 5260000000, 5280000000, 5300000000, 5320000000, 5500000000, 5540000000, 5745000000]
        # Create the labels list
        self._chan_labels = ['2.4 GHz  ch 1  - 2412 MHz', '2.4 GHz  ch 6  - 2437 MHz', '2.4 GHz  ch 11 - 2462 MHz', '5 GHz  ch 36 - 5180 MHz', '5 GHz  ch 40 - 5200 MHz', '5 GHz  ch 44 - 5220 MHz', '5 GHz  ch 48 - 5240 MHz', '5 GHz  ch 52 - 5260 MHz', '5 GHz  ch 56 - 5280 MHz', '5 GHz  ch 60 - 5300 MHz', '5 GHz  ch 64 - 5320 MHz', '5 GHz  ch 100 - 5500 MHz', '5 GHz  ch 108 - 5540 MHz', '5 GHz  ch 149 - 5745 MHz']
        # Create the combo box
        self._chan_tool_bar = Qt.QToolBar(self)
        self._chan_tool_bar.addWidget(Qt.QLabel("Wi-Fi channel" + ": "))
        self._chan_combo_box = Qt.QComboBox()
        self._chan_tool_bar.addWidget(self._chan_combo_box)
        for _label in self._chan_labels: self._chan_combo_box.addItem(_label)
        self._chan_callback = lambda i: Qt.QMetaObject.invokeMethod(self._chan_combo_box, "setCurrentIndex", Qt.Q_ARG("int", self._chan_options.index(i)))
        self._chan_callback(self.chan)
        self._chan_combo_box.currentIndexChanged.connect(
            lambda i: self.set_chan(self._chan_options[i]))
        # Create the radio buttons
        self.top_grid_layout.addWidget(self._chan_tool_bar, 0, 0, 1, 1)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_waterfall_sink_x_0 = qtgui.waterfall_sink_c(
            nfft, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            (int(chan + lo_offset)), #fc
            samp_rate, #bw
            "Waterfall - bursts over time", #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_waterfall_sink_x_0.set_update_time(0.10)
        self.qtgui_waterfall_sink_x_0.enable_grid(False)
        self.qtgui_waterfall_sink_x_0.enable_axis_labels(True)



        labels = ['RX1', '', '', '', '',
                  '', '', '', '', '']
        colors = [0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
                  1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_waterfall_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_waterfall_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_waterfall_sink_x_0.set_color_map(i, colors[i])
            self.qtgui_waterfall_sink_x_0.set_line_alpha(i, alphas[i])

        self.qtgui_waterfall_sink_x_0.set_intensity_range(-110, -20)

        self._qtgui_waterfall_sink_x_0_win = sip.wrapinstance(self.qtgui_waterfall_sink_x_0.qwidget(), Qt.QWidget)

        self.top_grid_layout.addWidget(self._qtgui_waterfall_sink_x_0_win, 6, 0, 4, 1)
        for r in range(6, 10):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            nfft, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            (int(chan + lo_offset)), #fc
            samp_rate, #bw
            "Spectrum - the channel sits 15 MHz above the DC spike", #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis((-110), 0)
        self.qtgui_freq_sink_x_0.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_0.enable_autoscale(False)
        self.qtgui_freq_sink_x_0.enable_grid(True)
        self.qtgui_freq_sink_x_0.set_fft_average(0.2)
        self.qtgui_freq_sink_x_0.enable_axis_labels(True)
        self.qtgui_freq_sink_x_0.enable_control_panel(True)
        self.qtgui_freq_sink_x_0.set_fft_window_normalized(False)



        labels = ['RX1', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_freq_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_freq_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_freq_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_freq_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_freq_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_0_win, 2, 0, 4, 1)
        for r in range(2, 6):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.iio_fmcomms2_source_0 = iio.fmcomms2_source_fc32(uri, [True, True, False, False], 32768)
        self.iio_fmcomms2_source_0.set_len_tag_key('packet_len')
        self.iio_fmcomms2_source_0.set_frequency((int(chan + lo_offset)))
        self.iio_fmcomms2_source_0.set_samplerate(samp_rate)
        if True:
            self.iio_fmcomms2_source_0.set_gain_mode(0, 'manual')
            self.iio_fmcomms2_source_0.set_gain(0, gain)
        if False:
            self.iio_fmcomms2_source_0.set_gain_mode(1, 'manual')
            self.iio_fmcomms2_source_0.set_gain(1, 0)
        self.iio_fmcomms2_source_0.set_quadrature(True)
        self.iio_fmcomms2_source_0.set_rfdc(True)
        self.iio_fmcomms2_source_0.set_bbdc(True)
        self.iio_fmcomms2_source_0.set_filter_params('Off', '', 0, 0)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.iio_fmcomms2_source_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.iio_fmcomms2_source_0, 0), (self.qtgui_waterfall_sink_x_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "fishball_wifi_live")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_uri(self):
        return self.uri

    def set_uri(self, uri):
        self.uri = uri

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.iio_fmcomms2_source_0.set_samplerate(self.samp_rate)
        self.qtgui_freq_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)
        self.qtgui_waterfall_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)

    def get_nfft(self):
        return self.nfft

    def set_nfft(self, nfft):
        self.nfft = nfft

    def get_lo_offset(self):
        return self.lo_offset

    def set_lo_offset(self, lo_offset):
        self.lo_offset = lo_offset
        self.iio_fmcomms2_source_0.set_frequency((int(self.chan + self.lo_offset)))
        self.qtgui_freq_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)
        self.qtgui_waterfall_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)

    def get_gain(self):
        return self.gain

    def set_gain(self, gain):
        self.gain = gain
        self.iio_fmcomms2_source_0.set_gain(0, self.gain)

    def get_chan(self):
        return self.chan

    def set_chan(self, chan):
        self.chan = chan
        self._chan_callback(self.chan)
        self.iio_fmcomms2_source_0.set_frequency((int(self.chan + self.lo_offset)))
        self.qtgui_freq_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)
        self.qtgui_waterfall_sink_x_0.set_frequency_range((int(self.chan + self.lo_offset)), self.samp_rate)




def main(top_block_cls=fishball_wifi_live, options=None):

    if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
        style = gr.prefs().get_string('qtgui', 'style', 'raster')
        Qt.QApplication.setGraphicsSystem(style)
    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
