# CONAN
COde for exoplaNet ANalysis

### Installation
Python package requirements:
numpy, scipy, matplotlib, mc3, batman

Fortran packages:
Routines from Mandel & Agol 2002, compiled with f2py:

```bash
git clone https://github.com/mlendl42/CONAN3.git
cd CONAN3

pip install -r requirements.txt

f2py -m occultquad -c occultquad.f
f2py -m occultnl -c occultnl.f

python setup.py develop

```

See recent changes in change_log.rst

