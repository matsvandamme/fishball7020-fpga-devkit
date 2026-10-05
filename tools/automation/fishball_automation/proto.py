"""The API's message types and method table, loaded from fishball.desc.

fishball.desc is fishball.proto compiled by protoc into a descriptor set: a
binary that every protobuf runtime reads the same way. Loading the types from
it at run time, instead of committing generated *_pb2.py files, is what lets
one copy of this package run on the board (Debian's protobuf 3.21) and on a PC
(whatever pip installs today): generated code is tied to the protoc version
that wrote it, a descriptor set is not.

    from fishball_automation import proto
    req = proto.ConfigureRequest(rx_lo_hz=868_000_000)
"""
import pathlib

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

SERVICE = "fishball.v1.Fishball"
PORT = 7020
_DESC = pathlib.Path(__file__).resolve().parent / "fishball.desc"

_pool = descriptor_pool.DescriptorPool()
_set = descriptor_pb2.FileDescriptorSet.FromString(_DESC.read_bytes())
for _f in _set.file:
    _pool.AddSerializedFile(_f.SerializeToString())


_classes = {}
_factory = None if hasattr(message_factory, "GetMessageClass") else message_factory.MessageFactory(_pool)


def _message_class(descriptor):
    """One class per message type, however often it is asked for: an older
    protobuf builds a new, unequal class on every call otherwise, and gRPC
    checks replies against the class it was given."""
    if descriptor.full_name not in _classes:
        _classes[descriptor.full_name] = (
            message_factory.GetMessageClass(descriptor) if _factory is None      # protobuf 4.22 and later
            else _factory.GetPrototype(descriptor))                               # 3.x to 4.21
    return _classes[descriptor.full_name]


_file = _pool.FindFileByName("fishball.proto")
for _name, _d in _file.message_types_by_name.items():
    globals()[_name] = _message_class(_d)

# name -> (request class, reply class, reply is a stream)
METHODS = {
    m.name: (_message_class(m.input_type), _message_class(m.output_type), m.server_streaming)
    for m in _file.services_by_name["Fishball"].methods
}


def path(method):
    """The gRPC path of a method: /fishball.v1.Fishball/GetStatus."""
    return f"/{SERVICE}/{method}"
