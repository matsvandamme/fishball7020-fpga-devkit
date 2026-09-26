"""Square QAM points, shared by the modulator and the EVM meter.

This is a GRC "Python Module" block, not a signal-processing block. Its
contents are available in parameter expressions anywhere in the flowgraph, so
`qam.points(order)` can feed the constellation object that the MODULATOR is
built from, while the same function decides what the EVM METER measures
against. One definition, both ends.

That matters more than it looks. An EVM meter holding its own idea of the
constellation is a meter that can read a healthy few percent while the
transmitter is sending something else entirely - the numbers stay plausible
because both sides are internally consistent and wrong together. Sharing the
function makes that failure impossible rather than unlikely.

`order` is 4 (QPSK), 16 or 64. Points come out with unit mean power.
"""

import numpy as np


def bits(order):
    """Bits per symbol. 2 for QPSK, 4 for 16-QAM, 6 for 64-QAM."""
    b = int(round(np.log2(order)))
    if 2 ** b != int(order):
        raise ValueError('order must be a power of two')
    return b


def points(order):
    """Unit-mean-power square QAM points, as a list of Python complex.

    Kept identical to examples/lib/evm_meter.py's square_qam(), which
    examples/test_blocks.py asserts.
    """
    m = int(round(np.sqrt(order)))
    if m * m != int(order) or m < 2:
        raise ValueError('order must be a square: 4, 16, 64 ...')
    lv = 2 * np.arange(m) - (m - 1)                  # -3 -1 1 3 for m = 4
    pts = (lv[:, None] + 1j * lv[None, :]).ravel()
    pts = pts / np.sqrt((np.abs(pts) ** 2).mean())
    return [complex(p) for p in pts]
