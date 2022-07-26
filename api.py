from datetime import date

import requests
import numpy as np
import xmltodict
import json

'''
This is the help page to figure out how to use the api correctly:
https://www.tidesandcurrents.noaa.gov/api-helper/url-generator.html

## To Get Accurate Predictions You Must Know That:

- Time is in hours starting from the first epoch date (from the 'datums' api - someone did not go to cowedge). At time of this writing this seems to be 1983-1-1. Buttt, they say they are in process of updating this as I write.
- Amplitudes can be given in feet or meters (check the api help page.)
- Speeds are given in degrees and need to be converted to radians for calculations.
- Phases are given in degrees and need to be converted to radians for calculations.
- Phases are given in local (with daylight savings?) and gmt, BUT you still have to account it with an offset when doing calcations. WHY? #FIXME
- A verticle intercept must be included `a cos(0)` as the harmonics are centered around zero. At the the time of writing this seems to be Lower Low Water LLW (find on the 'datums' api), but more stations need to be checked.
- Your first check should be against the first epoch day. Load up the station in NOAA tides and see if its close. You may need to account for timezone or verticle intercept differences. If you cant get the first day right, your not going to get any others.
https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id={YOUR STATIONID HERE}&units=standard&bdate=19830101&edate=19830102&timezone=LST&clock=12hour&datum=MLLW&interval=hilo&action=dailychart
'''

class Station:

    url = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{}.json?units=english'

    @classmethod
    def fromID(cls, id):
        r = requests.get(cls.url.format(id))
        return cls(json.loads(r.text))

    def __init__(self, j):

        station = j['stations'][0]
        self.id = station['id']
        self.name = station['name']
        self.lat = station['lat']
        self.lng = station['lng']
        self.type_type = station['tideType']
        self.state = station['state']
        self.timezone = station['timezone']
        self.timezonecorr = station['timezonecorr']

        self.harmonics = HarmonicConstituent.fromID(self.id)
        datums = StationDatums.fromID(self.id)
        self.epoch = datums.epoch
        self.datums = datums.datums
        llw = self.datums['MLLW'] #TODO check if this right
        print(33, llw)
        d = {
                'number': 99,
                'name': 'Z0',
                'description': 'vertical intercept',
                'amplitude': llw,
                'phase_GMT': 0,
                'phase_local': 0,
                'speed': 0,
        }
        self.harmonics.append(HarmonicConstituent('feet', d)) #FIXME feet or meter

    def __repr__(self):
        n = self.__class__.__name__
        return f'<{n} #{self.id} {self.name}, {self.state}>'


class StationDatums:
    url = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{}/datums.xml?units=english'
    @classmethod
    def fromID(cls, id):
        r = requests.get(cls.url.format(id))
        d = xmltodict.parse(r.text)
        return cls(d)

    def __init__(self, j):

        epoch = j['Datums']['epoch']
        epoch = int(epoch.split('-')[0])
        self._epoch = date(epoch, 1, 1)
        self._datums = {}
        for d in j['Datums']['Datum']:
            self._datums[d['name']] = float(d['value'])

    @property
    def epoch(self): return self._epoch

    @property
    def datums(self): return self._datums


class HarmonicConstituent:

    url = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{}/harcon.json?units=english'
    period_kinds = set(['terdiurnal', 'semidiurnal', 'diurnal', 'anual'])
    kinds = set(['solar', 'lunar', 'water'])

    @classmethod
    def fromID(cls, id):
        r = requests.get(cls.url.format(id))
        j = json.loads(r.text)
        units = j['units']
        harmonics = []
        for item in j['HarmonicConstituents']:
            harmonic = cls(units, item)
            harmonics.append(harmonic)
        return harmonics

    def __init__(self, units, j):

        self._units = units
        self._number = j['number']
        self._name = j['name']
        self._description = j['description']
        self._amplitude = j['amplitude']
        self._phase_GMT= j['phase_GMT']
        self._phase_local= j['phase_local']
        self._speed = j['speed']

    def __repr__(self):
        n = self.__class__.__name__
        return f'<{n} {self.number}:{self.name}>'
    
    @property
    def units(self): return int(self._units)
    @property
    def number(self): return int(self._number)
    @property
    def name(self): return self._name
    @property
    def description(self): return self._description
    @property
    def amplitude(self): return float(self._amplitude)
    @property
    def phase_GMT(self): return float(self._phase_GMT)
    @property
    def phase_local(self): return float(self._phase_local)
    @property
    def speed(self): return float(self._speed)
    @property
    def period(self): return 360 / float(self._speed)
    @property
    def kind(self):
        d = self.description.lower()
        if 'water' in d:
            return 'water'
        elif 'solar' in d:
            return 'solar'
        elif 'lunar' in d:
            return 'lunar'

    @property
    def period_kind(self):
        p = self.period
        if p < 12:
            return 'terdiurnal'
        elif p <= 14:
            return 'semidiurnal'
        elif p < 28:
            return 'diurnal'
        else:
            return 'anual'
            
    def _toRad(self, degree):
        return degree * (np.pi / 180)

    def xySine(self, start, end, inc=.1):
        hour = np.arange(start, end, inc);
        s = self._toRad(self.speed)
        p = self._toRad(self.phase_local)
        x = np.arange(start, end, inc)
        amplitude = self.amplitude * np.sin(s * x + p)
        return hour, amplitude

    def minmax(self, hour, amplitude):
        a = np.diff(np.sign(np.diff(amplitude))).nonzero()[0] + 1 # local min+max

        x, y = np.ones(len(a)), np.ones(len(a))
        for i, k in enumerate(a):
            x[i], y[i] = hour[k], amplitude[k]
        return x, y

    def _filter_min_max(self, x, y, cmp):
        x_out, y_out = list(), list()
        last = None
        for i, (xx, yy) in enumerate(zip(x, y)):
            if last and cmp(last, yy):
                x_out.append(xx)
                y_out.append(yy)
            last = yy
        return np.array(x_out), np.array(y_out)

    def _highWater(self, hour, amplitude):
        x, y = self.minmax(hour, amplitude)
        mask = (y > 0)
        x, y = x[mask], y[mask]
        return x, y

    def highWater(self, hour, amplitude):
        return self._highWater(hour, amplitude)

    def higherHighWater(self, hour, amplitude):
        x, y = self._highWater(hour, amplitude)
        return self._filter_min_max(x, y, lambda last,yy : last < yy)

    def lowerHighWater(self, hour, amplitude):
        x, y = self._highWater(hour, amplitude)
        return self._filter_min_max(x, y, lambda last,yy : last > yy)

    def _lowWater(self, hour, amplitude):
        x, y = self.minmax(hour, amplitude)
        mask = (y < 0)
        x, y = x[mask], y[mask]
        return x, y

    def lowWater(self, hour, amplitude):
        return self._lowWater(hour, amplitude)

    def lowerLowWater(self, hour, amplitude):
        x, y = self._lowWater(hour, amplitude)
        return self._filter_min_max(x, y, lambda last,yy : last > yy)

    def higherLowWater(self, hour, amplitude):
        x, y = self._lowWater(hour, amplitude)
        return self._filter_min_max(x, y, lambda last,yy : last < yy)

    def moving_average(self, x, n):
        #return np.convolve(x, np.ones(window_size), 'same' ) / window_size
        ret = np.cumsum(x, dtype='float')
        ret[n:] = ret[n:] - ret[:-n]
        return ret[n-1:]/n


class HarmonicGroup(HarmonicConstituent):
    def __init__(self, name, harmonics=[], description=''):
        self._name = name
        self._harmonics = list(harmonics)
        self._description = description

    @property
    def name(self): return self._name
    @property
    def harmonics(self): return list(self._harmonics)
    @property
    def description(self): return self._description

    def __repr__(self):
        n = self.__class__.__name__
        return f'<{n} {self.name}>'
    
    def append(self, item):
        self._harmonics.append(item)

    def __iter__(self): return iter(self._harmonics)

    def xySine(self, start, end, inc=.1):
        if not self._harmonics:
            raise ValueError('harmonics are empty')
        l = []
        for h in self._harmonics:
            hour, amplitude = h.xySine(start, end, inc=inc)
            l.append(amplitude)
        return hour, np.sum(l, axis=0)

    def filterByKind(self, kind, description=''):
        l = []
        for h in self:
            if kind not in h.kinds:
                raise ValueError(f'Unknown kind {repr(kind)}')
            if h.kind == kind:
                l.append(h)
        return self.__class__(kind, l, description)

    def filterByPeriod(self, kind, description=''):
        l = []
        for h in self:
            if kind not in h.period_kinds:
                raise ValueError(f'Unknown period_kind {repr(kind)}')
            if h.period_kind == kind:
                l.append(h)
        return self.__class__(kind, l, description)


if __name__ == '__main__':

    id = 9432780
    station = Station.fromID(id)
    print(station)
    print(station.datums)
    print(station.harmonics)
    print(station.epoch)

    import pickle

    with open('data/data.pickle', 'wb') as f:
        # Pickle the 'data' dictionary using the highest protocol available.
        pickle.dump(station, f, pickle.HIGHEST_PROTOCOL)


