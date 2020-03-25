from typing import Any, Dict, Iterable, Iterator, List, Optional, Union
from cached_property import cached_property, cached_property_with_ttl
from itertools import takewhile
import paramiko
import json
import re
import uu


class DictX(Dict):
    "dict with DictX({}) as default value"

    def __missing__(self, key: Any):
        return DictX({})

    # def __getattr__(self, attr: str) -> Any:
    #     return self[attr]

    def __str__(self) -> str:
        return '' if self == {} else super(DictX, self).__str__()


class Config(DictX):
    def __missing__(self, key: Any) -> Dict[str, str]:
        key = str(key)
        return Config({
            k[len(key)+1:]: v
            for (k, v) in self.items()
            if k.startswith(key + '.')
        })

    def __iter__(self) -> Iterator[Union[str, Dict[str, str]]]:
        if any(k.startswith('0.') for k in self.keys()):
            return takewhile(lambda x: x != {}, (self[i] for i in range(2**32)))
        elif any(k.startswith('1.') for k in self.keys()):
            return takewhile(lambda x: x != {}, (self[i] for i in range(1, 2**32)))
        else:
            return super(Config, self).__iter__()

    # Val_ = Union[str, int, bool, Dict[str, 'Val_']]

    def change(self, key: str, val: Union[str, int, Dict[str, Any]]):
        for k in list(filter(lambda x: x.startswith(key), self.keys())):
            del self[k]
        if isinstance(val, str):
            self[key] = val
        elif isinstance(val, bool):
            self[key] = 'enabled' if val else 'disabled'
        elif isinstance(val, int):
            self[key] = str(val)
        elif isinstance(val, Dict):
            for subkey in val.keys():
                self.change(key + '.' + subkey, val[subkey])
        else:
            raise TypeError

    def __str__(self):
        return "\n".join("{}={}".format(key, self[key]) for key in sorted(self.keys()))


class AirOS(paramiko.SSHClient):

    def __init__(self, hostname: str = '192.168.1.20', user: str = 'ubnt', password: str = 'ubnt'):
        super(AirOS, self).__init__()
        # self.load_system_host_keys()
        self.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        self.connect(hostname=hostname, username=user, password=password, timeout=30)

    def json_output(self, command: str) -> Union[Dict, List]:
        _stdin, stdout, _stderr = self.exec_command(command)
        return json.load(stdout, object_hook=lambda dct: DictX(dct))

    @cached_property
    def config(self) -> Config:
        _stdin, stdout, _stderr = self.exec_command('sort /tmp/system.cfg')
        return Config(
            {kv[0]: kv[1] for kv in map(lambda e: e.strip('\r\n').split('=', 1), stdout.readlines())})

    def read_config(self) -> Config:
        "Read /tmp/system.cfg to self.config dictionary"
        del self.__dict__['config']
        return self.config()
    
    def upgrade_fw(self, local_path: str) -> None:
        # No sftp in dropbear
        # with self.open_sftp() as sftp:
            # sftp.put(local_path, '/tmp/fwupdate.bin')
        stdin, _stdout, _stderr = self.exec_command('uudecode -o /tmp/fwupdate.bin')
        uu.encode(local_path, stdin, backtick=True)
        stdin.flush()
        stdin.close()
        self.exec_command('/sbin/fwupdate -m')

    @cached_property_with_ttl(ttl=5)
    def status(self) -> Union[Dict, List]:
        return self.json_output('ubntbox status')

    def read_status(self) -> Union[Dict, List]:
        del self.__dict__['status']
        return self.status # type: ignore

    @cached_property_with_ttl(ttl=5)
    def wstalist(self) -> Iterable[Dict]:
        return self.json_output('wstalist')

    def read_wstalist(self) -> Iterable[Dict]:
        del self.__dict__['wstalist']
        return self.wstalist # type: ignore

    @cached_property_with_ttl(ttl=5)
    def mcastatus(self) -> Dict[str, str]:
        _stdin, stdout, _stderr = self.exec_command('ubntbox mca-status')
        return {
            k: v
            for [k, v] in
            [
                s.split('=', 1)
                for s in re.split('[\r\n,]+', str(stdout.read().decode('UTF-8').strip()))
            ]
        }

    def read_mcastatus(self) -> Dict[str, str]:
        del self.__dict__['mcastatus']
        return self.mcastatus # type: ignore

    def save(self) -> str:
        "Save changed config to /tmp/system.cfg and write it to flash"
        self.save_candidate()
        _stdin, stdout, stderr = self.exec_command(
            'test -f /tmp/candidate.cfg && mv /tmp/candidate.cfg /tmp/system.cfg && cfgmtd -w -p /etc/ 2>&1')
        return stdout.read().decode('UTF-8')

    def save_candidate(self) -> None:
        "Dump candidate config (self.config property) to /tmp/candidate.cfg"
        stdin, stdout, _stderr = self.exec_command('sort > /tmp/candidate.cfg')
        stdin.write(str(self.config))
        stdin.flush()
        stdin.channel.close()

    def diff(self) -> str:
        "Diff changes with /tmp/system.cfg"
        self.save_candidate()
        # _stdin, stdout, _stderr = self.exec_command('test -f /tmp/candidate.cfg && sort /tmp/system.cfg | diff -U0 - /tmp/candidate.cfg')
        _stdin, stdout, _stderr = self.exec_command(
            'sort /tmp/system.cfg > /tmp/system.cfg.sorted; test -f /tmp/candidate.cfg && diff -U0 /tmp/system.cfg.sorted /tmp/candidate.cfg')
        return stdout.read().decode('UTF-8')

    def reboot(self) -> None:
        self.exec_command('sync; reboot')

    def is_station(self) -> bool:
        return self.config['radio.1.mode'] == 'managed' # type: ignore

    def is_ap(self) -> bool:
        return self.config['radio.1.mode'] == 'master' # type: ignore
    
    def interfaces_bridged_with(self, iface: str) -> List[str]:
        return next(
            (
                [port['devname'] for port in bridge['port'] if port['devname'] != iface]
                for bridge in self.config['bridge'] # type: ignore
                if iface in {port['devname'] for port in bridge['port']}
            ),
            [])

    def management_interface(self) -> Optional[str]:
        return next(
            (
                x['devname']
                for x in self.config['netconf'] # type: ignore
                if x['role'] == 'mlan'
            ),
            None)
