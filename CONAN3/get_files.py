# %%
import numpy as np
import os
import pandas as pd
import matplotlib.pyplot as plt
from astropy.io import fits

try:
    import lightkurve as lk
except:
    print("Warning: LightKurve not installed, won't be able to download TESS data. run `pip install lightkurve`")
try:
    from pycheops import Dataset
except:
    print("Warning: pycheops not installed, won't be able to download CHEOPS data. run `pip install pycheops`")
try:
    from dace_query.cheops import Cheops
except:
    print("Warning: dace_query not installed, won't be able to download CHEOPS data. run `pip install dace_query`")

class get_TESS_data(object):
    """
    Class to download and save TESS light curves from MAST (using the `lightkurve` package).

    Parameters
    ----------
    planet_name : str
        Name of the planet.

    Examples
    --------
    >>> from CONAN3.get_files import get_TESS_data
    >>> df = get_TESS_data("WASP-121")
    >>> df.search(author="SPOC", exptime=120)
    >>> df.download(sectors= [7,33,34,61], author="SPOC", exptime=120)
    >>> df.scatter()
    >>> df.save_CONAN_lcfile(bjd_ref = 2450000, folder="data")
    """

    def __init__(self, planet_name):
        self.planet_name = planet_name
        self.lc          = {}

    def search(self,sectors=None,author=None,exptime=None):
        """
        Search for TESS light curves on MAST using the lightkurve package.
        see documentation for lightkurve.search_lightcurve for more information.

        Parameters
        ----------
        sectors : int or list of ints
            TESS sectors to search for light curves.
        author : str
            Author of the light curve. Default is "SPOC".
        exptime : float
            Exposure time of the light curve.
        """
        self.author  = author
        self.sectors = sectors
        self.exptime = exptime

        print(lk.search_lightcurve(self.planet_name,author=self.author,sector=self.sectors,
                                   exptime=self.exptime, mission="TESS"))
        
    def download(self,sectors=None,author=None,exptime=None, select_flux="pdcsap_flux",quality_bitmask="hard"):
        """  
        Download TESS light curves from MAST using the lightkurve package

        Parameters
        ----------
        sectors : int or list of ints
            TESS sector lightcurve to download.
        author : str
            Author of the light curve. Default is "SPOC".
        exptime : float
            Exposure time of the light curve.
        quality_bitmask : str
            Quality bitmask to use for the lightkurve package. Default is "hard".
        """
        if sectors is not None: self.sectors = sectors
        if author  is not None: self.author  = author
        if exptime is not None: self.exptime = exptime
        # assert select_flux in ["pdcsap_flux","sap_flux"], "select_flux must be either 'pdcsap_flux' or 'sap_flux'"

        if isinstance(self.sectors,int): self.sectors = [self.sectors]

        for s in self.sectors:
            self.lc[s] = lk.search_lightcurve(self.planet_name,author=self.author,sector=s,
                                                exptime=self.exptime).download(quality_bitmask=quality_bitmask)
            try:
                self.lc[s] = self.lc[s].select_flux(select_flux)
            except:
                print(f"{select_flux} is not available. Using sap_flux instead.")
                self.lc[s] = self.lc[s].select_flux("sap_flux")

            self.lc[s]= self.lc[s].remove_nans().normalize()
            print(f"downloaded lightcurve for sector {s}")

    def discard_ramp(self,length=0.25):
        """
        Discard data at the begining of the orbits that typically feature ramps

        Parameters
        ----------
        length : float
            length of data (in days) to discard at beginning of each orbit.
        """

        assert self.lc != {}, "No light curves downloaded yet. Run `download()` first."
        for s in self.sectors:
            gap = np.diff(self.lc[s]) > 0.5
        #TODO: implement this
        raise NotImplemented

    def scatter(self):
        """
        Plot the scatter of the light curves.
        """
        assert self.lc != {}, "No light curves downloaded yet. Run `download()` first."
        for s in self.sectors:
            self.lc[s].scatter()
    
    def save_CONAN_lcfile(self,bjd_ref = 2450000, folder="data", out_filename=None):
        """
        Save TESS light curves as a CONAN light curve file.

        Parameters
        ----------
        bjd_ref : float
            BJD reference time to use for the light curve file.
        folder : str
            Folder to save the light curve file in.
        out_filename : str
            Name of the output file. Default is None in which case the file will be named as "{planet_name}_S{sector}.dat"
        """

        assert self.lc != {}, "No light curves downloaded yet. Run `download()` first."
        if not os.path.exists(folder): os.mkdir(folder)

        for s in self.sectors:
            try:
                t, f, e = self.lc[s]["time"].value, self.lc[s]["flux"].value.unmasked, self.lc[s]["flux_err"].value.unmasked   
            except AttributeError:
                t, f, e = self.lc[s]["time"].value, self.lc[s]["flux"].value, self.lc[s]["flux_err"].value
            t = t + 2457000 - bjd_ref
            file = f"{folder}/{self.planet_name}_S{s}.dat" if out_filename is None else f"{folder}/{out_filename}"
            np.savetxt(file, np.stack((t,f,e),axis=1),fmt='%.8f',
                        header=f'time-{bjd_ref} {"flux":10s} {"flux_err":10s}')
            print(f"saved file as: {file}")

class get_CHEOPS_data(object):
    """
    Class to download and save CHEOPS light curves from CHEOPS archive (using `dace_query` and `pycheops`).

    Parameters
    ----------
    planet_name : str
        Name of the planet.

    Examples
    --------
    >>> from CONAN3.get_files import get_CHEOPS_data
    >>> df = get_CHEOPS_data("KELT-20")
    >>> df.search( filters = { "pi_name":{"contains":["LENDL"]}, "data_arch_rev":{"equal":[3]} })
    >>> df.download(file_keys="all", aperture="DEFAULT")
    >>> df.scatter()
    >>> df.save_CONAN_lcfile(bjd_ref = 2450000, folder="data")
    """
    
    def __init__(self, planet_name):
        self.planet_name = planet_name
        self.lc          = []

    def search(self,filters=None):
        """   
        Query the cheops database to retrieve available visits. Filters and sorting order can be applied to the query via named arguments (see query_options)
        
        Parameters
        ----------
        filters : dict
            Dictionary of filters to apply to the query. 
            e.g. filters = {"pi_name":{"contains":["LENDL"]},"data_arch_rev":{"equal":[3]}} will return all visits of `planet_name` by PI:Lendl with data archive version 3.
        """
        self.filter = {'obj_id_catname': {'contains':[self.planet_name]}}
        self.filter.update(filters)

        data = Cheops.query_database(filters=self.filter, sort={"date_mjd_start":"asc"})
        self.file_keys = data["file_key"]
        print(pd.DataFrame(data, columns=["obj_id_catname","file_key", "pi_name", "date_mjd_start",
                                            "obs_total_exptime", "data_arch_rev",'status_published']))

    def download(self, file_keys="all", aperture="DEFAULT", decontaminate=True, reject_highpoints=True, verbose=True):
        """   
        Download CHEOPS light curves from the cheops database using the dace_query package

        Parameters
        ----------
        file_keys : list of str
            List of file keys to download. if "all" is given, all file_keys shown in `.search()` result will be downloaded.

        aperture : str
            Aperture to use for the light curve. Default is "DEFAULT". The options are: "R15","R16",...,"R40","RINF","RSUP".

        decontaminate : bool
            Decontaminate the light curve. Default is True.

        reject_highpoints : bool
            Reject high points in the light curve. Default is True. 
        """
        
        
        if isinstance(file_keys,str):
            if file_keys=="all": file_keys = self.file_keys 
            else: 
                file_keys = [file_keys]
        for f in file_keys: assert f in self.file_keys, f"file_key must be in {self.file_keys}"

        if isinstance(aperture,str): aperture = [aperture]*len(file_keys)
        elif isinstance(aperture, list): assert len(aperture)==len(file_keys), "aperture must be a single string or list of the same length as file_keys"

        for i,file_key in enumerate(file_keys):
            d     = Dataset(file_key,verbose=False)
            _,_,_ = d.get_lightcurve(aperture=aperture[i],decontaminate=decontaminate, reject_highpoints=reject_highpoints,verbose=False)
            if verbose: print(f"downloaded lightcurve with file key: {file_key}, aperture: {aperture[i]}")
            
            #remove points with high background
            mask  = d.lc["bg"] > 3*np.nanmedian(d.lc["bg"])
            _,_,_ = d.mask_data(mask, verbose=False)

            self.lc.append(d)

    def scatter(self, figsize=(10,4)):
        """
        Plot the scatter of the light curves.
        """
        assert self.lc != {}, "No light curves downloaded yet. Run `.download()` first."
        for d in self.lc:
            plt.figure(figsize=figsize)
            plt.scatter(d.lc["time"],d.lc["flux"],s=1, label=d.file_key)
            plt.legend()
            plt.xlabel(f"BJD - {d.bjd_ref}")
            plt.ylabel("Flux")
            plt.show()

    def save_CONAN_lcfile(self,bjd_ref = 2450000, folder="data", out_filename=None):
        """
        Save CHEOPS light curves as a CONAN light curve file.
        the output columns are [t, f, e, x_off, y_off, roll, bg, contam, deltaT]

        Parameters
        ----------
        bjd_ref : float
            BJD reference time to use for the light curve file.
        folder : str
            Folder to save the light curve file in.
        out_filename : str
            Name of the output file. Default is None in which case the file will be named as "{planet_name}_TG{file_key}.dat"
        """
    
        rescale   = lambda x: (x - np.min(x))/np.ptp(x)          # between 0 and 1 
        rescale_r = lambda x: (2*x-(x.min()+x.max()))/np.ptp(x)  #between -1 and 1 

        assert self.lc != {}, "No light curves downloaded yet. Run `.download()` first."
        if not os.path.exists(folder): os.mkdir(folder)
        
        for d in self.lc:
            t = d.lc["time"]+d.bjd_ref - bjd_ref
            
            lc_ = np.stack((t, d.lc["flux"], d.lc["flux_err"], rescale_r(d.lc["xoff"]),
                            rescale_r(d.lc["yoff"]), self._resort_roll(d.lc["roll_angle"]),
                            rescale(d.lc["bg"]), rescale(d.lc["contam"]), d.lc["deltaT"])).T
            
            fkey = d.file_key.split("TG")[-1].split("_V")[0]
            prefix = d.target
            file = folder+"/"+prefix+"_"+fkey+".dat" if out_filename is None else f"{folder}/{out_filename}"
            np.savetxt(file, lc_, fmt="%.8f", 
                        header=f'time-{bjd_ref} {"flux":10s} {"flux_err":10s} {"x_off":10s} {"y_off":10s} {"roll":10s} {"bg":10s} {"contam":10s} {"deltaT":10s}')
            print(f"saved file as {file}")

    def _resort_roll(self,x):
        #make roll-angle continuous
        x = x.copy()
        phi = np.sort(x)
        gap = np.diff(phi)
        if max(gap)>20:
            brk_pt = phi[np.argmax(gap)]+0.5*max(gap)
        else: brk_pt = 360
        # x = (360 + x - brk_pt)%360
        x[x > brk_pt] -= 360
        return x 



def get_EULER_data(FITS_filepath, out_folder=".", planet_name=None):
    """
    create .dat file for CONAN from the EULER fits file

    Parameters
    ----------
    FITS_filepath : str
        Path to the EULER fits file.

    Returns
    -------
    file:
        .dat file for CONAN
    """
    lc = fits.open(FITS_filepath)
    
    ti        = lc[1].data['time (BJD-TDB)'] -2450000
    fl        = lc[1].data['flux']
    fl_err    = lc[1].data['sflux']

    fwhm      = lc[1].data['fwhm']
    peak_flux = lc[1].data['peak']
    air_mass  = lc[1].data['airmass']
    sky       = lc[1].data['bkg']
    xshift    = lc[1].data['dx']
    yshift    = lc[1].data['dy']
    exptime   = lc[1].data['exptime']
    try:
        planet_name = lc[0].header["OBJECT"]
    except:
        planet_name = planet_name if planet_name is not None else ""
    
    np.savetxt(f'{out_folder}/lc_{planet_name}.dat', np.transpose([ti, fl, fl_err, xshift, yshift, air_mass, fwhm, sky, exptime]), fmt= '%3.5f')
    return

class get_EULER_data_from_server(object):
    """ 
    class to get EULER data from the server at Geneva Observatory. This requires some login access

    Parameters
    ----------
    planet_name : str
        Name of the planet.

    Examples
    --------
    >>> from CONAN3.get_files import get_EULER_data
    >>> df = get_EULER_data("WASP-121")
    >>> df.search(dates=["2020-09-01","2020-09-30"])
    >>> df.download(aperture="DEFAULT")
    >>> df.scatter()
    >>> df.save_CONAN_lcfile(bjd_ref = 2450000, folder="data")
    """
    def __init__(self, planet_name):
        self.planet_name = planet_name
        self.lc          = []
        Warning("This class is not yet implemented")

    def search(self,date_range=None):
        """
        Search for EULER light curves (pipeline fits files?) on the server at Geneva Observatory between the given dates.

        Parameters
        ----------
        date_range : list of str
            List of dates to search for light curves. Format is ["YYYY-MM-DD","YYYY-MM-DD].
        """
        self.date_range = date_range
        self.files = []
        for date in self.date_range:
            self.files += self._get_files(date)
        self.files = np.unique(self.files)
        print(f"found {len(self.files)} files")

    def download(self, file_name, aperture="DEFAULT"):
        """
        Download EULER light curves from the server at Geneva Observatory.

        Parameters
        ----------
        file_name : str
            Name of the file to download.
        aperture : str
            Aperture to use for the light curve. Default is "DEFAULT". The options are: "R15","R16",...,"R40","RINF","RSUP".
        """
        self.file_name = file_name
        self.aperture  = aperture
        self.lc = []
        for f in self.files:
            if f.split("/")[-1] == self.file_name:
                self.lc.append(self._get_lc(f,aperture=self.aperture))
        print(f"downloaded {len(self.lc)} light curves")

    def scatter(self, figsize=(10,4)):
        """
        Plot the scatter of the light curves.
        """
        assert self.lc != [], "No light curves downloaded yet. Run `.download()` first."
        for d in self.lc:
            plt.figure(figsize=figsize)
            plt.scatter(d["time"],d["flux"],s=1, label=d.file_key)
            plt.legend()
            plt.xlabel(f"BJD - {d.bjd_ref}")
            plt.ylabel("Flux")
            plt.show()

    def save_CONAN_lcfile(self,bjd_ref = 2450000, folder="data"):
        """
        Save EULER light curves as a CONAN light curve file.

        Parameters
        ----------
        bjd_ref : float
            BJD reference time to use for the light curve file.
        folder : str
            Folder to save the light curve file in.
        """
        rescale   = lambda x: (x - np.min(x))/np.ptp(x)          # between 0 and 1 
        rescale_r = lambda x: (2*x-(x.min()+x.max()))/np.ptp(x)

        assert self.lc != [], "No light curves downloaded yet. Run `.download()` first."
        if not os.path.exists(folder): os.mkdir(folder)






def get_parameters(planet_name, database="exoplanetarchive", table="pscomppars", overwrite_cache=False):
    """
    get stellar and planet parameters from nasa exoplanet archive or exoplanet.eu

    Parameters
    ----------
    planet_name : str
        Name of the planet.
    database : str
        Database to use. Default is "exoplanetarchive". Options are "exoplanetarchive" or "exoplanet.eu".
    overwrite_cache : bool
        Overwrite the cached parameters. Default is True.
    """
    if os.path.exists(f"{planet_name}_sysparams.pkl") and overwrite_cache is False:
        print("Loading parameters from cache ...")
        params = pd.read_pickle(f"{planet_name}_sysparams.pkl")
        return params
    
    params = {"star":{}, "planet":{}}

    assert database in ["exoplanetarchive","exoplanet.eu"], "database must be either 'exoplanetarchive' or 'exoplanet.eu'"

    if database == "exoplanetarchive":
        from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

        print("Getting system parameters from NASA exoplanet archive ...")
        if table=="pscomppars":
            df = NasaExoplanetArchive.query_object(planet_name,table=table)
        elif table=="ps":
            df = NasaExoplanetArchive.query_object(planet_name,table=table) 
            df = df[df['default_flag']==1]
        else: 
            raise ValueError("table must be either 'pscomppars' or 'ps'")
        
        df = df.to_pandas()
        

        params["star"]["Teff"]     = (df["st_teff"][0],df["st_tefferr1"][0])
        params["star"]["logg"]     = (df["st_logg"][0],df["st_loggerr1"][0])
        params["star"]["FeH"]      = (df["st_met"][0],df["st_meterr1"][0])
        params["star"]["radius"]   = (df["st_rad"][0], df["st_raderr1"][0])
        params["star"]["mass"]     = (df["st_mass"][0],df["st_masserr1"][0])
        params["star"]["density"]  = (df["st_dens"][0],df["st_denserr1"][0])

        params["planet"]["name"]   = df["pl_name"][0]
        params["planet"]["period"] = (df["pl_orbper"][0],df["pl_orbpererr1"][0])
        params["planet"]["rprs"]   = (df["pl_ratror"][0],df["pl_ratrorerr1"][0])
        params["planet"]["mass"]   = (df["pl_bmassj"][0],df["pl_bmassjerr1"][0])
        params["planet"]["ecc"]    = (df["pl_orbeccen"][0],df["pl_orbeccenerr1"][0])
        params["planet"]["w"]      = (df["pl_orblper"][0],df["pl_orblpererr1"][0])
        params["planet"]["T0"]     = (df["pl_tranmid"][0],df["pl_tranmiderr1"][0])
        params["planet"]["b"]      = (df["pl_imppar"][0],df["pl_impparerr1"][0])
        params["planet"]["T14"]    = (df["pl_trandur"][0],df["pl_trandurerr1"][0])
        params["planet"]["aR"]     = (df["pl_ratdor"][0],df["pl_ratdorerr1"][0])
        params["planet"]["K[m/s]"] = (df["pl_rvamp"][0],df["pl_rvamperr1"][0])
    else:
        raise NotImplemented

    pd.to_pickle(params, f"{planet_name}_sysparams.pkl")

    return params
