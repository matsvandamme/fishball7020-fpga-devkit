# The automation server: drive the board from your measurement scripts

A small server on the board, and a Python client for your PC. A script asks
for things at the level of the task ("set 868 MHz at 20 MS/s, record two
million samples from both receivers, give me the file") and the server does
the board's part. It is modelled on the Saleae Logic 2 automation API.

**This version never transmits.** No call can raise a transmitter; `mute`
is always allowed. Full page: [docs/automation.md](../../docs/automation.md).

```bash
# run from: the repo root on your PC
./devkit automation install      # once: the server onto the board, as a service
./devkit automation status       # the board, the radio, the clock, who holds the buffers
./devkit automation smoke        # an end-to-end check, receive only
```

```python
# run from: tools/automation, as: .venv/bin/python example.py
from fishball_automation.client import Fishball

with Fishball("fishball.local") as board:
    board.configure(rx_lo_hz=868_000_000, sample_rate_hz=20_000_000)
    rec = board.capture(samples=2_000_000, channels=[1, 2], path="loop")
    x = rec.read()                       # complex64, shape (2, 2000000)
```

`./devkit automation status` creates the client's venv (`tools/automation/.venv`)
on first use. To make it yourself:

```bash
# run from: tools/automation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_automation.py     # 40 tests against a fake board; no board needed
```

| File | |
|---|---|
| `fishball.proto` | the API: nine calls and their messages. Any gRPC client in any language can use it |
| `fishball_automation/server.py` | the server; runs on the board, port 7020 |
| `fishball_automation/backend.py` | the board behind one interface: sysfs and `iio_readdev` for real, a fake for the tests |
| `fishball_automation/client.py` | the Python client |
| `fishball_automation/proto.py`, `fishball.desc` | the message types, loaded from the compiled `.proto` at run time |
| `fishball-automation.service` | the systemd unit; like `iiod`, it starts only if the boot-time transmitter mute was confirmed |
| `automation.sh` | what `./devkit automation` runs |

After editing `fishball.proto`, rebuild the descriptor:

```bash
# run from: tools/automation
protoc --descriptor_set_out=fishball_automation/fishball.desc --include_imports fishball.proto
```
