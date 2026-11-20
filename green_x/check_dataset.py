import csv,sys
from pathlib import Path
from PIL import Image
p=Path(sys.argv[1] if len(sys.argv)>1 else 'output/dataset')
with (p/'labels.csv').open() as f: rows=list(csv.DictReader(f))
assert rows, 'No labels found'
for i,row in enumerate(rows):
    with Image.open(p/'images'/row['filename']) as im:
        w,h=im.size
    x,y=float(row['x']),float(row['y'])
    assert 0<=x<w and 0<=y<h,(i,row)
print(f'PASS: {len(rows)} labeled images, all centers inside image')
