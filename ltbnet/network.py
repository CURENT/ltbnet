import sys
import re
import json
import time
import csv

from mininet.topo import Topo
from mininet.link import Intf, TCIntf

from mininet import log
from mininet.node import Node

from ltbnet.utils import check_intf
from ltbnet.minipmu import MiniPMU


class Network(Topo):
    """Network configuration class"""
    def __init__(self):
        super(Network, self).__init__()
        self.Region = Region()
        self.Switch = Switch()
        self.PDC = PDC()
        self.Router = Router()
        self.PMU = PMU()
        self.Link = Link()
        self.HwIntf = HwIntf()
        self.TCHwIntf = TCHwIntf()

        self.components = []

    def add(self, config, **kwargs):
        for item in config:
            ty = item['Type']

            if hasattr(self, ty):
                self.__dict__[ty].add(**item)
                if ty not in self.components:
                    self.components.append(ty)

    def setup(self, config):
        """Convenient function wrapper to setup a network from config"""
        self.add(config)
        self.setup_by_region()
        self.build_mn_name()
        self.assign_ip()
        self.add_node_to_mn()
        self.add_link_to_mn()
        return self

    def make_dump(self):
        """Prepare data in a list of lines from a CSV file. The first line is the header, and the following lines
        are the data entries
        """
        lines = []

        header = ['Idx', 'Type', 'Region', 'Name', 'Longitude', 'Latitude', 'MAC', 'IP',
                  'PMU_IDX', 'From', 'To', 'Delay', 'BW', 'Loss', 'Jitter']
        lines.append(header)

        for item in self.components:
            lines.extend(self.__dict__[item].dump())
        return lines

    def dump_csv(self, path=None):
        """Dump the configuration to a csv file"""
        lines = self.make_dump()

        f = open(path, 'w') if path else sys.stdout

        for line in lines:
            f.write(','.join(str(x) for x in line))
            f.write('\n')

        f.close()

    def dump_json(self, path=None):
        """Dump the configuration to a json file"""
        lines = self.make_dump()

        fp = open(path, 'w') if path else sys.stdout

        data = []
        header = lines[0]
        for i in range(1, len(lines)):
            line = lines[i]
            line_dct = {}

            for key, val in zip(header, line):
                line_dct[key] = val
            data.append(line_dct)

        out = json.dump(data, fp, indent=4)

    def setup_by_region(self):
        """Set up component information in Regions. Store PMU.idx in Region.pmu for each region"""

        for item in self.components:
            if not hasattr(self.Region, item):
                continue

            self.Region.__dict__[item] = [list() for _ in range(self.Region.n)]

            for i in range(self.__dict__[item].n):
                name = self.__dict__[item].name[i]
                idx= self.__dict__[item].idx[i]
                region = self.__dict__[item].region[i]

                if region in self.Region.idx:
                    loc = self.Region.name.index(region)
                else:
                    log.error('Region <{r}> of {comp} <{name}> is undefined.'.format(r=region, comp=item, name=name))
                    continue

                self.Region.__dict__[item][loc].append(idx)

    def build_mn_name(self):
        """Build Mininet node names for the components"""
        for item in self.components:
            self.__dict__[item].build_mn_name()

    def assign_ip(self, base='192.168.1.'):
        """Assign IP address in a LAN"""

        # for item in self.components:
        #     self.__dict__[item].ip = [''] * self.__dict__[item].n

        count = 1

        # for PDCs
        # self.PDC.ip = [''] * self.PDC.n
        for i in range(self.PDC.n):
            count += 1
            if self.PDC.ip[i]:
                continue
            self.PDC.ip[i] = base + str(count)

        # for PMUs
        # self.PMU.ip = [''] * self.PMU.n
        for i in range(self.PMU.n):
            count += 1
            if self.PMU.ip[i]:
                continue

            self.PMU.ip[i] = base + str(count)

    def add_node_to_mn(self):
        for item in self.components:
            # log.info('Adding {n} <{ty}> to the network...'.format(n=self.__dict__[item].n, ty=item))
            self.__dict__[item].add_node_to_mn(self)

    def add_link_to_mn(self):
        for item in self.components:
            # log.info('Adding links to {ty}...'.format(ty=item))
            self.__dict__[item].add_link_to_mn(self)

    def to_canonical(self, idx):
        if idx in self.Switch.idx:
            return self.Switch.mn_name[self.Switch.idx.index(idx)]
        else:
            return idx

    def add_hw_intf(self, net):
        """Add hardware interfaces from Network.HwIntf records"""
        for i, name, to in zip(range(self.HwIntf.n), self.HwIntf.name, self.HwIntf.to):
            switch_index = self.Switch.lookup_index(to)
            log.info('*** Adding hardware interface', name, 'to switch', to, '\n')

            r = Intf(name, node=net.switches[switch_index])

    def add_tc_hw_intf(self, net):
        """Add traffic controlled hardware interfaces from Network.TCHwIntf records"""
        for i, name, to, delay, bw, loss, jitter in zip(
                range(self.TCHwIntf.n), self.TCHwIntf.name, self.TCHwIntf.to, self.TCHwIntf.delay, self.TCHwIntf.bw,
                      self.TCHwIntf.loss, self.TCHwIntf.jitter):
            switch_index = self.Switch.lookup_index(to)

            d = delay
            b = float(bw) if bw is not None else None
            l = float(loss) if loss is not None else None
            j = float(jitter) if jitter is not None else None

            log.info('*** Adding traffic controlled hardware interface', name, 'to switch', to, '\n')
            log.info('')
            r = TCIntf(name, node=net.switches[switch_index], delay=d, loss=l, bw=b, jitter=j)

    def dump_sw_port_node(self, net):
        """
        Dump the switch-port-host mapping

        Returns
        -------

        """
        idx_list = []
        sw_list = []
        sw_mac_list = []
        sw_id_list = []
        sw_intf_name_list = []
        sw_intf_id_list = []
        target_intf_name_list = []
        target_node_name_list = []

        header = ['Idx', 'Switch', 'Switch_ID', 'MAC', 'Port', "Switch_Intf", "Node_Intf", "Node_Name"]
        for idx, sw_name, sw_id in zip(self.Switch.idx, self.Switch.name, self.Switch.mn_object):
            sw_instance = net.nameToNode[sw_id]
            sw_mac = sw_instance.dpid

            for intf_id, intf_instance in sw_instance.intfs.items():
                if intf_instance.name == 'lo':
                    continue  # skip the loop-back interface

                if intf_instance.link is None:
                    print('***Warning: Intf_id <{}> has no instance'.format(intf_id))
                    continue

                link1 = intf_instance.link.intf1
                link2 = intf_instance.link.intf2

                if any([link1, link2]) is None:
                    continue

                source_intf_name = None
                target_intf = None
                if sw_id in link1.name:
                    source_intf_name = link1.name
                    target_intf = link2
                elif sw_id in link2.name:
                    source_intf_name = link2.name
                    target_intf = link1

                assert target_intf is not None

                target_intf_name = target_intf.name
                target_name = target_intf.node.name

                idx_list.append(idx)
                sw_list.append(sw_name)
                sw_id_list.append(sw_id)
                sw_mac_list.append(sw_mac)
                sw_intf_name_list.append(source_intf_name)
                sw_intf_id_list.append(intf_id)
                target_intf_name_list.append(target_intf_name)
                target_node_name_list.append(target_name)

        with open("sw_port_node.csv", 'w') as f:
            writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            writer.writerow(header)
            for item in zip(idx_list, sw_list, sw_id_list, sw_mac_list, sw_intf_id_list, sw_intf_name_list,
                                 target_intf_name_list, target_node_name_list):
                writer.writerow(item)







class Record(object):
    """Base class for config.csv records"""
    def __init__(self):
        self._name = type(self).__name__

        self.n = 0
        self.idx = []
        self.name = []
        self.coords = []
        self.mac = []
        self.pmu_idx = []
        self.delay = []
        self.bw = []
        self.jitter = []
        self.loss = []
        self.ip = []
        self.fr = []
        self.to = []
        self.region = []
        self.prefix = ''
        self.connections = []
        self.mn_name = []
        self.mn_object = []

        self.build()

    def build(self):
        """Custom build function"""
        pass

    def add(self, Type=None, Longitude=None, Latitude=None, MAC=None,
            Idx=None, Name='', Region='', IP='',
            PMU_IDX='', Delay='', BW='', Loss='', Jitter='', From='', To='', **kwargs):

        if not self._name:
            log.error('Device name not initialized')
            return

        if Type != self._name:
            return

        mac = None if MAC == 'None' else MAC
        idx = self._name + '_' + str(self.n) if not Idx else Idx
        pmu_idx = None if PMU_IDX == 'None' else int(PMU_IDX)

        if idx in self.idx:
            log.error('PMU Idx <{i}> conflict.'.format(i=idx))

        def to_type(var):
            """Helper function to convert field to a list or a None object """
            if var == 'None':
                out = None
            else:
                out = var
            return out

        delay = to_type(Delay)
        bw = to_type(BW)
        loss = to_type(Loss)
        jitter = to_type(Jitter)
        fr = to_type(From)
        to = to_type(To)

        lat = None if Latitude == 'None' else float(Latitude)
        lon = None if Longitude == 'None' else float(Longitude)

        self.name.append(Name)
        self.region.append(Region)
        self.coords.append((lat, lon))
        self.ip.append(IP)

        self.mac.append(mac)
        self.idx.append(idx)
        # self.connections.append(conn)

        self.pmu_idx.append(pmu_idx)
        self.delay.append(delay)
        self.bw.append(bw)
        self.loss.append(loss)
        self.jitter.append(jitter)
        self.fr.append(fr)
        self.to.append(to)

        self.n += 1

    def lookup_index(self, idx, canonical=False):
        """Return the numerical index of the the element `idx`"""
        records = self.idx
        if canonical:
            records = self.mn_name

        if idx not in records:
            return -1
        return records.index(idx)

    def dump(self):
        """Return a string of the dumped records in csv format"""
        ret = []

        # TODO: fix deprecated function

        for i in range(self.n):

            line = [self.idx[i],
                    self._name,
                    self.region[i],
                    self.name[i],
                    str(self.coords[i][1]),
                    str(self.coords[i][0]),
                    self.mac[i] if self.mac[i] else 'None',
                    self.ip[i] if self.ip[i] else 'None',
                    self.pmu_idx[i] if self.pmu_idx[i] else 'None',
                    self.delay[i] if self.pmu_idx[i] else 'None',
                    self.bw[i] if self.bw[i] else 'None',
                    self.loss[i] if self.loss[i] else 'None',
                    self.jitter[i] if self.jitter[i] else 'None'
                    ]

            ret.append(line)

        return ret

    def build_mn_name(self):
        """Build names to be used in Mininet"""
        self.mn_name = [''] * self.n
        for i in range(self.n):
            self.mn_name[i] = self.prefix + self.idx[i]

    def check_consistency(self):
        """Check consistency of Region definitions"""
        pass

    def add_node_to_mn(self, network):
        """Method to add all elements to a Mininet Topology"""
        if self._name not in ('Switch', 'Router', 'PDC', 'PMU'):
            return

        for i, name, ip in zip(range(self.n), self.mn_name, self.ip):
            mac = self.mac[i]
            if self._name == 'Switch':
                n = network.addSwitch(name, dpid=mac)
                self.mn_object.append(n)
            else:
                n = network.addHost(name, ip=ip, mac=mac)
                self.mn_object.append(n)
                # log.debug('Adding {ty} <{n}, {ip}> to network.'.format(ty=self._name, n=name, ip=ip))

    def add_link_to_mn(self, network):
        pass


class Region(Record):
    """Data streaming Region class"""
    def build(self):
        self.Switch = []  # list of network switches
        self.Router = []  # list of network routers
        self.PMU = []
        self.PDC = []


class PMU(Record):
    """Data streaming PMU node class"""
    def run_pmu(self, network):
        """Run MiniPMU on the defined PMU nodes"""
        run_minipmu = 'minipmu {port} {pmu_idx} -n={name}'
        for i in range(self.n):
            name = self.mn_name[i]
            node = network.get(name)
            pmu_name = self.name[i]
            pmu_idx = self.pmu_idx[i]

            if pmu_name[:4] != 'PMU_':
                pmu_name = 'PMU_' + name
            call_str = run_minipmu.format(port=1410,
                                          pmu_idx=pmu_idx,
                                          name=pmu_name,
                                          )

            node.popen(call_str)
            log.info('{name} idx={idx} started\n'.format(name=pmu_name, idx=pmu_idx))
            time.sleep(0.02)


class PDC(Record):
    """Data streaming PDC class"""
    pass


class Switch(Record):
    """Data streaming network switch class"""

    def build_mn_name(self):
        """Build canonical switch name such as `s23`"""
        self.mn_name = [''] * self.n
        for i in range(self.n):
            self.mn_name[i] = 's' + str(i)


class Router(Record):
    """Data streaming network router class"""
    pass


class Link(Record):
    """Link storage"""
    def __init__(self):
        super(Link, self).__init__()
        self.links = []
        self.obj = []

    def register(self, fr, to, idx):
        self.links.append((fr, to))
        self.obj.append(idx)

    def exist_undirectioned(self, fr, to):
        """Check if the undirectional path from `fr` to `to` exists"""

        if self.exist_directioned(fr, to) or self.exist_directioned(to, fr):
            return True
        else:
            return False

    def exist_directioned(self, fr, to):
        """Check if the directional path from `fr` to `to` exists"""
        ret = False
        if (fr, to) in self.links:
            ret = True

        return ret

    def add_link_to_mn(self, network):
        """Method to add links from each element to the connections"""

        for i, name, fr, to, delay, bw, loss, jitter in \
                zip(range(self.n), self.mn_name, self.fr, self.to, self.delay, self.bw, self.loss, self.jitter):

            fr = network.to_canonical(fr)
            to = network.to_canonical(to)

            # check for optional link configs
            d = delay
            b = float(bw) if bw is not None else None

            l = None
            if loss:
                l = float(loss)
            j = float(jitter) if jitter is not None else None

            if not network.Link.exist_undirectioned(fr, to):
                r = network.addLink(fr, to, delay=d, bw=b, loss=l, jitter=j)
                # register the link element to the LTBNet object
                network.Link.register(fr, to, r)
                # log.debug('Adding link <{fr}> to <{to}>.'.format(fr=name, to=c))


class HwIntf(Record):
    """Hardware Interface class"""
    def add_link_to_mn(self, network):
        pass


class TCHwIntf(Record):
    """Hardware Traffic controlled Interface class"""
    def add_link_to_mn(self, network):
        pass
