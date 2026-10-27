"""Readable log ticks and exact, non-interpolated hover samples."""
import math
import numpy as np
import pyqtgraph as pg

def readable_log_ticks(low, high, pixels, minimum_spacing=34):
    if not all(math.isfinite(v) for v in (low, high, pixels)) or high <= low or pixels <= 0:
        return []
    low, high = max(-290., low), min(290., high)
    if high <= low:
        return []
    candidates = []
    if high-low < .35:
        a,b = 10**low,10**high
        target = max(2, int(pixels/minimum_spacing))
        rough = (b-a)/target
        base = 10**math.floor(math.log10(rough))
        step = next((factor*base for factor in (1,2,5,10) if factor*base >= rough),10*base)
        first = math.ceil(a/step)*step
        for i in range(min(100, max(0,int((b-first)/step)+1))):
            value = first+i*step
            if value > 0:
                candidates.append((0, math.log10(value)))
    else:
        for exponent in range(math.floor(low), math.ceil(high)+1):
            for multiplier in range(1,10):
                value = exponent+math.log10(multiplier)
                if low-1e-10 <= value <= high+1e-10:
                    priority = 0 if multiplier == 1 else 1 if multiplier in (2,5) else 2
                    candidates.append((priority,value))
    selected = []
    for _,value in sorted(candidates):
        if all(abs(value-other)*pixels/(high-low) >= minimum_spacing for other in selected):
            selected.append(value)
    return sorted(selected)

class ReadableAxis(pg.AxisItem):
    def logTickValues(self,minVal,maxVal,size,stdTicks):
        return [(1.,readable_log_ticks(minVal,maxVal,size))]
    def logTickStrings(self,values,scale,spacing):
        return [f'{10**value:.5g}' for value in values]

def nearest_sample(data, stamp):
    """Return a real nearest sample and its time; never interpolate across missing values."""
    if data is None or len(data)==0 or stamp < data[0,0] or stamp > data[-1,0]+2:
        return None
    index=int(np.searchsorted(data[:,0],stamp))
    candidates=[i for i in (index-1,index) if 0 <= i < len(data)]
    index=min(candidates,key=lambda i:abs(data[i,0]-stamp))
    actual,value=data[index]
    if not math.isfinite(value):
        return None
    return float(actual),float(value)
