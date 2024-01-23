import numpy as np
import matplotlib.pyplot as plt
import corner
import pickle
from types import SimpleNamespace
import os
import matplotlib
import pandas as pd
from lmfit import minimize, Parameters, Parameter
import batman
from warnings import warn
from ldtk import SVOFilter
from .utils import outlier_clipping, rho_to_aR, rho_to_tdur, rescale0_1, rescale_minus1_1, cosine_atm_variation 
from .utils import phase_fold, supersampling, convert_LD
from copy import deepcopy
from scipy.interpolate import LSQUnivariateSpline

__all__ = ["load_lightcurves", "load_rvs", "fit_setup", "load_result", "__default_backend__","load_result_array"]

#helper functions
__default_backend__ = matplotlib.get_backend()
matplotlib.use(__default_backend__)

def _plot_data(obj, plot_cols, col_labels, nrow_ncols=None, figsize=None, 
                fit_order=0, model_overplot=None):
    """
    Takes a data object (containing light-curves or RVs) and plots them.
    """

    n_data = len(obj._names)
    tsm= True if plot_cols[0]==0 else False
    cols = plot_cols+(1,) if len(plot_cols)==2 else plot_cols
    input_data = obj._input_lc if obj._obj_type=="lc_obj" else obj._input_rv

    if plot_cols[1] == "res": 
        cols = (cols[0],1,2)
        col_labels = (col_labels[0],"residuals")

    if n_data == 1:
        # p1, p2, p3 = np.loadtxt(obj._fpath+obj._names[0], usecols=cols, unpack=True )
        p1, p2, p3 = [input_data[obj._names[0]][f"col{n}"] for n in cols]
        if plot_cols[1] == "res": p2 = model_overplot[0].residual

        if len(plot_cols)==2: p3 = None
        if figsize is None: figsize=(8,5)
        fig = plt.figure(figsize=figsize)
        plt.errorbar(p1,p2,yerr=p3, fmt=".", color="b", ecolor="gray",label=f'{obj._names[0]}')
        if model_overplot and plot_cols[1] != "res":
            plt.plot(p1,model_overplot[0].tot_trnd_mod,"r",zorder=3,label="detrend_model")
            if tsm: plt.plot(model_overplot[0].time_smooth,model_overplot[0].planet_mod_smooth,"c",zorder=3,label="planet_model")   #smooth model plot if time on x axis
            else: plt.plot(p1,model_overplot[0].planet_mod,"c",zorder=3,label="planet_model")


        if fit_order>0:
            pfit = np.polyfit(p1,p2,fit_order)
            srt = np.argsort(p1)
            plt.plot(p1[srt],np.polyval(pfit,p1[srt]),"r",zorder=3)
        plt.legend(fontsize=12)

    else:
        if nrow_ncols is None: 
            nrow_ncols = (int(n_data/2), 2) if n_data%2 ==0 else (int(np.ceil(n_data/3)), 3)
        if figsize is None: figsize=(14,3*nrow_ncols[0])
        fig, ax = plt.subplots(nrow_ncols[0], nrow_ncols[1], figsize=figsize)
        ax = ax.reshape(-1)

        for i, d in enumerate(obj._names):
            # p1,p2,p3 = np.loadtxt(obj._fpath+d,usecols=cols, unpack=True )
            p1,p2,p3 = [input_data[d][f"col{n}"] for n in cols]
            if plot_cols[1] == "res": p2 = model_overplot[i].residual

            if len(plot_cols)==2: p3 = None
            ax[i].errorbar(p1,p2,yerr=p3, fmt=".", color="b", ecolor="gray",label=f'{obj._names[i]}')
            if model_overplot and plot_cols[1] != "res":
                ax[i].plot(p1,model_overplot[i].tot_trnd_mod,"r",zorder=3,label="detrend_model")
                if tsm: ax[i].plot(model_overplot[i].time_smooth,model_overplot[i].planet_mod_smooth,"c",zorder=3,label="planet_model")
                else: ax[i].plot(p1,model_overplot[i].planet_mod,"c",zorder=3,label="planet_model")

            if fit_order>0:
                pfit = np.polyfit(p1,p2,fit_order)
                srt = np.argsort(p1)
                ax[i].plot(p1[srt],np.polyval(pfit,p1[srt]),"r",zorder=3)
            
            ax[i].legend(fontsize=12)
    fig.suptitle(f"{col_labels[0]} against {col_labels[1]}", y=0.99, fontsize=18)

    plt.show()
    return fig

def _skip_lines(file, n):
    """
    takes a open file object and skips the reading of lines by n lines
    
    """
    for i in range(n):
        dump = file.readline()
        
def _reversed_dict(d):
    """
    reverse the order of dictionary keys
    """
    dd = dict()
    for key in reversed(list(d.keys())):
        dd[key] = d[key]
    return dd

def _raise(exception_type, msg):
    raise exception_type(msg)

def _decorr(df, T_0=None, Period=None, rho_star=None,  Impact_para=0, RpRs=None, Eccentricity=0, omega=90, 
                D_occ=0, A_pc=0, ph_off=0, q1=0, q2=0,
                mask=False, decorr_bound=(-1,1), spline=None,ss_exp=None,
                offset=None, A0=None, B0=None, A3=None, B3=None,
                A4=None, B4=None, A5=None, B5=None,
                A6=None, B6=None, A7=None, B7=None,
                npl=1,return_models=False):
    """
    linear decorrelation with different columns of data file. It performs a linear model fit to the columns of the file.
    It uses columns 0,3,4,5,6,7 to construct the linear trend model. A spline can also be included to decorrelate against any column.
    
    Parameters:
    -----------
    df : dataframe/dict;
        data file with columns 0 to 8 (col0-col8).
    
    T_0, Period, rho_star, D_occ, Impact_para, RpRs, Eccentricity, omega,A_pc,ph_off : floats, None;
        transit/eclipse parameters of the planet. T_0 and P must be in same units as the time axis (cols0) in the data file. rho_star is the stellar density in g/cm^3.
        if float/int, the values are held fixed. if tuple/list of len 2 implies [min,max] while len 3 implies [min,start_val,max].
        
    q1,q2 : float  (optional);
        Kipping quadratic limb darkening parameters.

    mask : bool ;
        if True, transits and eclipses are masked using T_0, P and rho_star which must be float/int.                    
        
    offset, Ai, Bi; floats [-1,1] or None;
        coefficients of linear model where offset is the intercept. they have large bounds [-1,1].
        Ai, Bi are the linear and quadratic term of the model against column i. A0*col0 + A0*col0**2 for time trend
    
    spline : dict;
        spline configuration to use in decorrelation an axis of the data. Default is None which implies no spline is used.
        the config is given as a dict with keys "col", "knot_spacing", "degree" specifying the column, the knot spacing and the degree of the spline.
        e.g. spline = {"col":0, "knot_spacing":0.1, "degree":3} will fit a spline the flux as a function ofcolumn 0 with knot spacing of 0.1 and degree 3.

    npl : int; 
        number of planets in the system. default is 1.
        
    return_models : Bool;
        True to return trend model and transit/eclipse model.

    Returns:
    -------
    result: object;
        result object from fit with several attributes such as result.bestfit, result.params, result.bic, ...
        if return_models = True, returns (trend_model, transit/eclipse model)
    """
    DA = locals().copy()
    assert isinstance(spline, dict) or spline is None, "spline must be a dictionary"

    
    #transit variables
    pl_vars = ["T_0", "Period", "rho_star", "D_occ", "Impact_para","RpRs", "Eccentricity", "omega", "A_pc", "ph_off", "q1","q2"]
    tr_pars = {}
    for p in pl_vars:
        for n in range(npl):
            lbl = f"_{n+1}" if npl>1 else ""                      # numbering to add to parameter names of each planet
            if p not in ["q1","q2","rho_star","A_pc","ph_off","D_occ"]:   # parameters common to all planet or not used in multi-planet fit
                tr_pars[p+lbl]= DA[p][n]  #transit/eclipse pars
            else:
                tr_pars[p] = DA[p]        #limb darkening pars

    #decorr variables    
    decorr_vars = [f"{L}{i}" for i in [0,3,4,5,6,7] for L in ["A","B"]]  + ["offset"]
    in_pars     = {k:v for k,v in DA.items() if k in decorr_vars}


    df       = pd.DataFrame(df)  #pandas dataframe
    col0_med = np.median(df["col0"])

    if mask:
        assert npl==1, "masking transits/eclipses only works for single planet systems"
        print("masking transit/eclipse phases")
        for tp in pl_vars:
            if isinstance(tr_pars[tp], tuple):
                if len(tr_pars[tp])==2:   tr_pars[tp]=tr_pars[tp][0]
                elif len(tr_pars[tp])==3: tr_pars[tp]=tr_pars[tp][1]
        #use periodicity of 0.5*P to catch both transits and eclipses. this does not work for eccentric orbits
        E = np.round(( col0_med - tr_pars['T_0'])/(0.5*tr_pars["Period"]) )
        Tc = E*(0.5*tr_pars["Period"]) + tr_pars['T_0']
        duration = rho_to_tdur(tr_pars["rho_star"], tr_pars["Impact_para"], tr_pars["RpRs"],tr_pars["Period"], tr_pars["Eccentricity"], tr_pars["omega"])
        phase = phase_fold(df["col0"], 0.5*tr_pars["Period"], Tc,-0.25)
        mask = abs(phase) > 0.5*duration/(0.5*tr_pars["Period"])
        # plt.plot(df["col0"],df["col1"],"r.")
        df = df[mask]
        # plt.plot(df["col0"],df["col1"],"b.")
        # plt.show()

        
    

    #decorr params
    params = Parameters()
    for key in in_pars.keys():
        val  = in_pars[key] if in_pars[key] != None else 0    #val is set to 0 or the value of the parameter
        vary = False if in_pars[key] is None else True
        params.add(key, value=val, min=decorr_bound[0], max=decorr_bound[1], vary=vary)
    
    #transit/eclipseparameters
    tr_params = Parameters()
    for key in tr_pars.keys():
        if isinstance(tr_pars[key], (list,tuple)):
            assert len(tr_pars[key]) in [2,3],f"{key} must be float/int or tuple of length 2/3"
            if len(tr_pars[key])==3:  #uniform prior (min, start, max)
                val = tr_pars[key]
                tr_params.add(key, value=val[1], min=val[0], max=val[2], vary=True)
            if len(tr_pars[key])==2: #normal prior (mean, std)
                tr_params[key] = Parameter(key, value=tr_pars[key][0], vary=True, user_data = tr_pars[key] )
        if isinstance(tr_pars[key], (float,int)):
            tr_params.add(key, value=tr_pars[key], vary=False)
        if tr_pars[key] == None:
            vs = ["RpRs","Period","rho_star"]
            vs = [v+(f"_{n+1}" if npl>1 else "") for n in range(npl) for v in vs]    
            val = 1e-10 if key in vs else 0 #allows to obtain transit/eclipse with zero depth
            tr_params.add(key, value=val, vary=False)
                
    
    def transit_occ_model(tr_params,t=None,ss_exp=ss_exp,npl=1):
        if t is None: t = df["col0"].values
        ss = supersampling(ss_exp/(60*24),int(ss_exp)) if ss_exp is not None else None
        tt_ss   = ss.supersample(t) if ss is not None else t

        model_flux = np.zeros_like(tt_ss)

        for n in range(1,npl+1):
            lbl = f"_{n}" if npl>1 else ""
            
            bt = batman.TransitParams()
            bt.per = tr_params["Period"+lbl]
            bt.t0  = tr_params["T_0"+lbl]
            bt.rp  = tr_params["RpRs"+lbl]
            b      = tr_params["Impact_para"+lbl]
            bt.ecc = tr_params["Eccentricity"+lbl]
            bt.w   = tr_params["omega"+lbl]
            bt.a   = rho_to_aR(tr_params["rho_star"], bt.per)
            bt.fp  = tr_params["D_occ"]                                        
            ecc_factor=(1-bt.ecc**2)/(1+bt.ecc*np.sin(np.deg2rad(bt.w)))  
            
            bt.inc = np.rad2deg(np.arccos(b/(bt.a * ecc_factor)))
            bt.limb_dark = "quadratic"
            
            u1,u2  = convert_LD(tr_params["q1"],tr_params["q2"],conv="q2u")
            bt.u   = [u1,u2]

            bt.t_secondary = bt.t0 + 0.5*bt.per*(1 + 4/np.pi * bt.ecc * np.cos(np.deg2rad(bt.w))) #eqn 33 (http://arxiv.org/abs/1001.2010)
            m_tra = batman.TransitModel(bt, tt_ss,transittype="primary")
            m_ecl = batman.TransitModel(bt, tt_ss,transittype="secondary")

            f_tra = m_tra.light_curve(bt)
            if tr_params["A_pc"] != 0:
                f_occ = rescale0_1(m_ecl.light_curve(bt))

                phase  = phase_fold(tt_ss, bt.per, bt.t0)
                atm    = cosine_atm_variation(phase,bt.fp, tr_params["A_pc"], tr_params["ph_off"])
            
                model_flux += (f_tra + f_occ*atm.pc)-1           #transit, eclipse, atm model
            else:
                f_occ = m_ecl.light_curve(bt)
                model_flux += f_tra + (f_occ - (1+bt.fp)) - 1                   #transit, eclipse, no PC

            model_flux = ss.rebin_flux(model_flux) if ss is not None else model_flux #rebin the model to the original cadence

        return np.array(1+model_flux)


    def trend_model(params):
        trend = 1 + params["offset"]       #offset
        trend += params["A0"]*(df["col0"]-col0_med)  + params["B0"]*(df["col0"]-col0_med)**2 #time trend
        trend += params["A3"]*df["col3"]  + params["B3"]*df["col3"]**2 #x
        trend += params["A4"]*df["col4"]  + params["B4"]*df["col4"]**2 #y
        trend += params["A5"]*df["col5"]  + params["B5"]*df["col5"]**2
        trend += params["A6"]*df["col6"]  + params["B6"]*df["col6"]**2 #bg
        trend += params["A7"]*df["col7"]  + params["B7"]*df["col7"]**2 #conta
        return np.array(trend)
    

    if spline is not None:
        spl_col = spline["col"]
        spl_kn  = spline["knot_spacing"]
        spl_deg = spline["degree"]
        assert spl_col in [0,3,4,5,6,7], f'_decorr(): spline["col"] must be one of [0,3,4,5,6,7]'

        spl_x = df["col"+str(spl_col)]
        srt   = np.argsort(spl_x)
        knots = np.arange(min(spl_x)+spl_kn,max(spl_x),spl_kn)

    if return_models:
        tra_occ_mod = transit_occ_model(tr_params,npl=npl)
        trnd_mod    = trend_model(params)
        fl_mod      = tra_occ_mod*trnd_mod

        if spline is not None:
            splfunc    = LSQUnivariateSpline(spl_x[srt],(df["col1"]-fl_mod)[srt],t=knots,k=spl_deg)
            spl_mod    = splfunc(spl_x)
        else: spl_mod  = 0
        
        tsm = np.linspace(min(df["col0"]),max(df["col0"]),len(df["col0"])*3)
        mods = SimpleNamespace(tot_trnd_mod       = trnd_mod+spl_mod, 
                                planet_mod        = tra_occ_mod, 
                                time_smooth       = tsm, 
                                planet_mod_smooth = transit_occ_model(tr_params,tsm,npl=npl), 
                                residual          = df["col1"] - fl_mod - spl_mod
                                ) 
        return mods
    
    #perform fitting 
    def chisqr(fit_params):
        flux_model = trend_model(fit_params)*transit_occ_model(fit_params,npl=npl)
        resid = df["col1"] - flux_model
        if spline is not None:
            splfunc = LSQUnivariateSpline(spl_x[srt],resid[srt],t=knots,k=spl_deg)
            spl     = splfunc(spl_x)
        else:
            spl = 0

        res = (resid-spl)/df["col2"]
        for p in fit_params:
            u = fit_params[p].user_data  #obtain tuple specifying the normal prior if defined
            if u:  #modify residual to account for how far the value is from mean of prior
                res = np.append(res, (u[0]-fit_params[p].value)/u[1] )
        # print(f"chi-square:{np.sum(res**2)}")
        return res
    
    fit_params = params+tr_params
    out = minimize(chisqr, fit_params, nan_policy='propagate')
    
    #modify output object
    tra_occ_mod = transit_occ_model(out.params,npl=npl)
    trnd_mod    = trend_model(out.params)
    spl_mod     = 0 if spline is None else LSQUnivariateSpline(spl_x[srt],(df["col1"]-tra_occ_mod*trnd_mod)[srt],t=knots,k=spl_deg)(spl_x)

    out.bestfit    = tra_occ_mod*trnd_mod + spl_mod
    out.poly_trend = trnd_mod   
    out.trend      = trnd_mod+spl_mod
    out.transit    = tra_occ_mod
    out.spl_mod    = spl_mod
    out.spl_x      = 0 if spline is None else spl_x
    
    out.time       = np.array(df["col0"])
    out.flux       = np.array(df["col1"])
    out.flux_err   = np.array(df["col2"])
    out.data       = df

    out.rms        = np.std(out.flux - out.bestfit)
    out.ndata      = len(out.time)
    out.residual   = out.residual[:out.ndata]    #note that residual = (y-mod)/err
    out.nfree      = out.ndata - out.nvarys
    out.chisqr     = np.sum(out.residual**2)
    out.redchi     = out.chisqr/out.nfree
    out.lnlike     = -0.5*np.sum(out.residual**2 + np.log(2*np.pi*out.flux_err**2))
    out.bic        = out.chisqr + out.nvarys*np.log(out.ndata)

    return out


def _decorr_RV(df, T_0=None, Period=None, K=None, sesinw=0, secosw=0, gamma=None, decorr_bound=(-1000,1000),
                A0=None, B0=None, A3=None, B3=None, A4=None, B4=None, A5=None, B5=None, npl=1,return_models=False):
    """
    linear decorrelation with different columns of data file. It performs a linear model fit to the 3rd column of the file.
    It uses columns 0,3,4,5 to construct the linear trend model.
    
    Parameters:
    -----------
    df : dataframe/dict;
        data file with columns 0 to 5 (col0-col5).
    
    T_0, Period, K, Eccentricity, omega : floats, None;
        RV parameters of the planet. T_0 and P must be in same units as the time axis (cols0) in the data file.
        if float/int, the values are held fixed. if tuple/list of len 2 implies [min,max] while len 3 implies [min,start_val,max].

    offset, Ai, Bi; floats [-1,1] or None;
        coefficients of linear model where offset is the systemic velocity. They have large bounds [-1000,1000].
        Ai, Bi are the linear and quadratic term of the model against column i. A0*col0 + A0*col0**2 for time trend
    
    npl : int; 
        number of planets in the system. default is 1.
        
    return_models : Bool;
        True to return trend model and transit/eclipse model.
         
    Returns:
    -------
    result: object;
        result object from fit with several attributes such as result.bestfit, result.params, result.bic, ...
        if return_models = True, returns (trend_model, transit/eclipse model)
    """
    from CONAN3.RVmodel_v3 import get_RVmod

    DA      = locals().copy()
    rv_pars = {}

    df       = pd.DataFrame(df)      #pandas dataframe
    col0_med = np.median(df["col0"])
                          

    #add indices to parameters if npl>1
    for p in ["T_0", "Period", "K", "sesinw", "secosw"]:
        for n in range(npl):
            lbl = f"_{n+1}" if npl>1 else ""   # numbering to add to parameter names of each planet
            rv_pars[p+lbl]= DA[p][n]           # rv pars
    rv_pars["gamma"] = DA["gamma"]   #same for all planets

    #decorr variables    
    decorr_vars = [f"{L}{i}" for i in [0,3,4,5] for L in ["A","B"]] 
    in_pars = {k:v for k,v in DA.items() if k in decorr_vars}  #dictionary of decorr parameters Ai,Bi

    #decorr params to fit or fix
    params = Parameters()
    for key in in_pars.keys():
        val  = in_pars[key] if in_pars[key] != None else 0
        vary = True if in_pars[key] != None else False
        params.add(key, value=val, min=decorr_bound[0], max=decorr_bound[1], vary=vary)
    
    #rvparameters
    rv_params = Parameters()
    for key in rv_pars.keys():
        if isinstance(rv_pars[key], (list,tuple)):
            assert len(rv_pars[key]) in [2,3],f"{key} must be float/int or tuple of length 2/3"
            if len(rv_pars[key])==3:  #uniform prior (min, start, max)
                val = rv_pars[key]
                rv_params.add(key, value=val[1], min=val[0], max=val[2], vary=True)
            if len(rv_pars[key])==2: #normal prior (mean, std)
                rv_params[key] = Parameter(key, value=rv_pars[key][0], vary=True, user_data = rv_pars[key] )
        if isinstance(rv_pars[key], (float,int)):
            rv_params.add(key, value=rv_pars[key], vary=False)
        if rv_pars[key] is None:
            rv_params.add(key, value=0, vary=False)
                
    
    def rv_model(rv_params,t=None,npl=1):
        if t is None: t = df["col0"].values
        rvmod = np.zeros_like(t)

        for n in range(1,npl+1):
            lbl = f"_{n}" if npl>1 else ""

            per     = [rv_params["Period"+lbl]]
            t0      = [rv_params["T_0"+lbl]]
            K       = [rv_params["K"+lbl]]
            sesinw  = [rv_params["sesinw"+lbl]]
            secosw  = [rv_params["secosw"+lbl]]
            mod,_   = get_RVmod(t, t0, per, K, sesinw, secosw, planet_only=True)  
            rvmod += mod
        
        # rvmod_kms = rvmod_ms/1000 # to km/s
        return rvmod + rv_params["gamma"]


    def trend_model(params):
        trend  = params["A0"]*(df["col0"]-col0_med)  + params["B0"]*(df["col0"]-col0_med)**2 #time trend
        trend += params["A3"]*df["col3"]  + params["B3"]*df["col3"]**2 #bisector
        trend += params["A4"]*df["col4"]  + params["B4"]*df["col4"]**2 #fwhm
        trend += params["A5"]*df["col5"]  + params["B5"]*df["col5"]**2 #contrast
        return np.array(trend)
    

    if return_models:
        tsm = np.linspace(min(df["col0"]),max(df["col0"]),max(500,len(df["col0"])*3))
        mods = SimpleNamespace(tot_trnd_mod = trend_model(params)+rv_params["gamma"], 
                                planet_mod  = rv_model(rv_params,npl=npl), 
                                time_smooth = tsm, 
                                planet_mod_smooth = rv_model(rv_params,tsm,npl=npl), 
                                residual    = df["col1"] - trend_model(params) - rv_model(rv_params,npl=npl)
                                )
        return mods
        
    #perform fitting 
    def chisqr(fit_params):
        rvmod = trend_model(fit_params)+rv_model(fit_params,npl=npl)
        res = (df["col1"] - rvmod)/df["col2"]
        for p in fit_params:
            u = fit_params[p].user_data  #obtain tuple specifying the normal prior if defined
            if u:  #modify residual to account for how far the value is from mean of prior
                res = np.append(res, (u[0]-fit_params[p].value)/u[1] )
        return res
    
    fit_params = params+rv_params
    out = minimize(chisqr, fit_params, nan_policy='propagate')
    
    #modify output object
    out.bestfit = trend_model(out.params)+rv_model(out.params,npl=npl)
    out.trend   = out.poly_trend = trend_model(out.params)+out.params["gamma"]
    out.rvmodel = rv_model(out.params,npl=npl)
    out.time    = np.array(df["col0"])
    out.rv      = np.array(df["col1"])
    out.rv_err  = np.array(df["col2"])
    out.data    = df
    out.rms     = np.std(out.rv - out.bestfit)
    out.ndata   = len(out.time)
    out.residual= out.residual[:out.ndata]    #out.residual = chisqr(out.params)
    out.nfree   = out.ndata - out.nvarys
    out.chisqr  = np.sum(out.residual**2)
    out.redchi  = out.chisqr/out.nfree
    out.lnlike  = -0.5*np.sum(out.residual**2 + np.log(2*np.pi*out.rv_err**2))
    out.bic     = out.chisqr + out.nvarys*np.log(out.ndata)

    return out


def _print_output(self, section: str, file=None):
    """function to print to screen/file the different sections of CONAN setup"""

    lc_possible_sections = ["lc_baseline", "gp", "planet_parameters", "depth_variation",
                            "phasecurve", "limb_darkening", "contamination"]
    rv_possible_sections = ["rv_baseline", "rv_gp"]
    fit_possible_sections = ["fit", "stellar_pars"]

    if self._obj_type == "lc_obj":
        assert section in lc_possible_sections, f"{section} not a valid section of `lc_obj`. Section must be one of {lc_possible_sections}."
        max_name_len = max([len(n) for n in self._names]+[len("name")])      #max length of lc filename
        max_filt_len = max([len(n) for n in self._filters]+[len("filt")])  #max length of lc filter name
    if self._obj_type == "rv_obj":
        assert section in rv_possible_sections, f"{section} not a valid section of `rv_obj`. Section must be one of {rv_possible_sections}."
        max_name_len = max([len(n) for n in self._names]+[len("name")])      #max length of lc filename
    if self._obj_type == "fit_obj":
        assert section in fit_possible_sections, f"{section} not a valid section of `fit_obj`. Section must be one of {fit_possible_sections}."

    if section == "lc_baseline":
        _print_lc_baseline = """# ============ Input lightcurves filters baseline function =======================================================""" +\
                            f""" \n{"name":{max_name_len}s} {"filt":{max_filt_len}s} {"𝜆_𝜇m":5s}|{"s_samp ":7s} {"clip   ":7s} {"scl_col":7s}|{"col0":4s} {"col3":4s} {"col4":4s} {"col5":4s} {"col6":4s} {"col7":4s}|{"sin":3s} {"id":2s} {"GP":2s} {"spline_config  ":15s}"""
        #define print out format
        txtfmt = f"\n{{0:{max_name_len}s}} {{1:{max_filt_len}s}}"+" {2:5s}|{3:7s} {4:7s} {5:7s}|{6:4d} {7:4d} {8:4d} {9:4d} {10:4d} {11:4d}|{12:3d} {13:2d} {14:2s} {15:15s}"        
        for i in range(len(self._names)):
            t = txtfmt.format(self._names[i], self._filters[i], str(self._lamdas[i]), self._ss[i].config,self._clipped_data.config[i], self._rescaled_data.config,
                              *self._bases[i][:-1], self._groups[i], self._useGPphot[i],self._lcspline[i].conf, 
                                )
            _print_lc_baseline += t
        print(_print_lc_baseline, file=file)   

    if section == "gp":
        DA = self._GP_dict
        _print_gp = f"""# ==================== Photometry GP properties =================================================================="""+\
                     f"""\n{"name":{max_name_len}s} {'par1':4s} {"kern1":5s} {'Amplitude1_ppm':18s} {'length_scale':17s} |{'op':2s}| {'par2':4s} {"kern2":5s} {'Amplitude2_ppm':18s} {'length_scale2':17s}"""
        if DA != {}: 
            #define gp print out format
            txtfmt = f"\n{{0:{max_name_len}s}}"+" {1:4s} {2:5s} {3:18s} {4:17s} |{5:2s}| {6:4s} {7:5s} {8:18s} {9:17s} "        

            for lc in DA.keys():
                ngp = DA[lc]["ngp"]
                prior={}
                for p in ["amplitude", "lengthscale"]:
                    for j in range(ngp):
                        if DA[lc][p+str(j)].to_fit == "n":
                            prior[p+str(j)] = f"F({DA[lc][p+str(j)].start_value})"
                        elif DA[lc][p+str(j)].to_fit == "y" and DA[lc][p+str(j)].prior == "n":
                            b_lo = 0 if DA[lc][p+str(j)].bounds_lo==1e-20 else DA[lc][p+str(j)].bounds_lo
                            prior[p+str(j)] = f"LU({b_lo},{DA[lc][p+str(j)].start_value},{DA[lc][p+str(j)].bounds_hi})"
                        elif DA[lc][p+str(j)].to_fit == "y" and DA[lc][p+str(j)].prior == "p":
                            prior[p+str(j)] = f"N({DA[lc][p+str(j)].prior_mean},{DA[lc][p+str(j)].prior_width_lo})"

                if ngp == 2:
                    t = txtfmt.format(lc,DA[lc]["amplitude0"].user_data[1], DA[lc]["amplitude0"].user_data[0],  
                                                    prior["amplitude0"], prior["lengthscale0"], DA[lc]["op"], 
                                        DA[lc]["amplitude1"].user_data[1], DA[lc]["amplitude1"].user_data[0],
                                                    prior["amplitude1"], prior["lengthscale1"])
                else:
                    t = txtfmt.format(lc,DA[lc]["amplitude0"].user_data[1], DA[lc]["amplitude0"].user_data[0],  
                                                    prior["amplitude0"], prior["lengthscale0"], "--", 
                                        "None", "None", "None", "None")

                _print_gp += t
        print(_print_gp, file=file)

    if section == "planet_parameters":
        DA = self._config_par
        _print_planet_parameters = f"""# ============ Planet parameters (Transit and RV) setup ========================================================== """+\
                                    f"""\n{'name':12s}\tfit\tprior"""
        #define print out format
        txtfmt = "\n{0:12s}\t{1:3s}\t{2:}"
        #print line for stellar density
        p = "rho_star"
        pri_par = f"N({DA[f'pl{1}'][p].prior_mean},{DA[f'pl{1}'][p].prior_width_lo})" if DA[f'pl{1}'][p].prior == "p" else f"U({DA[f'pl{1}'][p].bounds_lo},{DA[f'pl{1}'][p].start_value},{DA[f'pl{1}'][p].bounds_hi})" if DA[f'pl{1}'][p].bounds_hi else f"F({DA[f'pl{1}'][p].start_value})"
        _print_planet_parameters +=  txtfmt.format( p, DA[f'pl{1}'][p].to_fit, pri_par)
        _print_planet_parameters +=  "\n---------------------"
        #then cycle through parameters for each planet       
        for n in range(1,self._nplanet+1):        
            for i,p in enumerate(self._TR_RV_parnames):
                if p != "rho_star":
                    pri_par = f"N({DA[f'pl{n}'][p].prior_mean},{DA[f'pl{n}'][p].prior_width_lo})" if DA[f'pl{n}'][p].prior == "p" else f"U({DA[f'pl{n}'][p].bounds_lo},{DA[f'pl{n}'][p].start_value},{DA[f'pl{n}'][p].bounds_hi})" if DA[f'pl{n}'][p].bounds_hi else f"F({DA[f'pl{n}'][p].start_value})"
                    t = txtfmt.format(  p+(f"_{n}" if self._nplanet>1 else ""), DA[f'pl{n}'][p].to_fit, pri_par)
                    _print_planet_parameters += t
            if n!=self._nplanet: _print_planet_parameters += "---------------------"
        print(_print_planet_parameters, file=file)

    if section == "depth_variation":
        grnames    = np.array(list(sorted(set(self._groups))))
        ngroup     = len(grnames)
        _print_depth_variation = f"""# ============ ddF setup ========================================================================================"""+\
                                    f"""\n{"Fit_ddFs":8s}\t{"dRpRs":10s}\tdiv_white"""

        #define print out format
        txtfmt = "\n{0:8s}\t{1:10s}\t{2:3s}"        
        pri_ddf = f"N({self._ddfs.drprs_op[4]},{self._ddfs.drprs_op[5]})" if self._ddfs.drprs_op[5] else f"U({self._ddfs.drprs_op[2]},{self._ddfs.drprs_op[0]},{self._ddfs.drprs_op[3]})"
        t = txtfmt.format(self._ddfs.ddfYN, pri_ddf, self._ddfs.divwhite)
        _print_depth_variation += t
        # _print_depth_variation += "\ngroup_ID   RpRs_0   err\t\tdwfile"
        # txtfmt = "\n{0:6d}\t   {1:.4f}   {2:.2e}   {3}"
        # for i in range(ngroup):
        #     t2 = txtfmt.format( grnames[i] , self._ddfs.depth_per_group[i],
        #                         self._ddfs.depth_err_per_group[i],f"dw_00{grnames[i]}.dat")
        #     _print_depth_variation += t2

        print(_print_depth_variation, file=file)

    if section == "phasecurve":
        pars = ["D_occ", "A_pc", "ph_off"]
        _print_phasecurve = f"""# ============ Phase curve setup ================================================================================ """+\
                                f"""\n{'filt':{max_filt_len}s}  {'param':6s}  fit \tprior"""
        #define print out format
        txtfmt = f"\n{{0:{max_filt_len}s}}"+"  {1:6s}  {2:3s} \t{3:}"       
        
        for par in pars:
            DA = self._PC_dict[par]
            for i,f in enumerate(self._filnames):
                pri_PC = f"N({DA[f].prior_mean},{DA[f].prior_width_lo})" if DA[f].prior == "p" else f"U({DA[f].bounds_lo},{DA[f].start_value},{DA[f].bounds_hi})" if DA[f].bounds_hi else f"F({DA[f].start_value})" 
                t = txtfmt.format( f, par, DA[f].to_fit, pri_PC)
                _print_phasecurve += t
            if par != pars[-1]: _print_phasecurve +=  "\n" +"-"*max_filt_len+"--------"
        print(_print_phasecurve, file=file)

    if section == "limb_darkening":
        DA = self._ld_dict
        _print_limb_darkening = f"""# ============ Limb darkening setup ============================================================================= """+\
                                f"""\n{'filters':7s}\tfit\t{'q_1':17s}\t{'q_2':17s}"""
        #define print out format
        txtfmt = "\n{0:7s}\t{1:3s}\t{2:17s}\t{3:17s}"       
        for i in range(len(self._filnames)):
            pri_q1 = f"N({DA['q1'][i]},{DA['sig_lo1'][i]})" if DA['sig_lo1'][i] else f"U({DA['bound_lo1'][i]},{DA['q1'][i]},{DA['bound_hi1'][i]})"  if DA['bound_hi1'][i] else f"F({DA['q1'][i]})"
            pri_q2 = f"N({DA['q2'][i]},{DA['sig_lo2'][i]})" if DA['sig_lo2'][i] else f"U({DA['bound_lo2'][i]},{DA['q2'][i]},{DA['bound_hi2'][i]})" if DA['bound_hi2'][i] else f"F({DA['q2'][i]})"
            to_fit = "y" if (pri_q1[0]!="F" or pri_q2[0]!="F") else "n"
            t = txtfmt.format(self._filnames[i], to_fit, pri_q1, pri_q2) 
            _print_limb_darkening += t

        print(_print_limb_darkening, file=file)

    if section == "contamination":
        DA = self._contfact_dict
        _print_contamination = f"""# ============ contamination setup (give contamination as flux ratio) ======================================== """+\
                                f"""\n{'filters':7s}\tcontam_factor"""
        #define print out format
        txtfmt = "\n{0:7s}\t{1}"       
        for i in range(len(self._filnames)):
            t = txtfmt.format(self._filnames[i],f'F({DA["cont_ratio"][i][0]})')
            _print_contamination += t
        print(_print_contamination, file=file)

    if section == "stellar_pars":
        DA = self._stellar_dict
        _print_stellar_pars = f"""# ============ Stellar input properties ======================================================================"""+\
        f"""\n{'# parameter':13s}   value """+\
        f"""\n{'Radius_[Rsun]':13s}  N({DA['R_st'][0]:.3f},{DA['R_st'][1]:.3f})"""+\
        f"""\n{'Mass_[Msun]':13s}  N({DA['M_st'][0]:.3f},{DA['M_st'][1]:.3f})"""+\
            f"""\nInput_method:[R+rho(Rrho), M+rho(Mrho)]: {DA['par_input']}"""
        print(_print_stellar_pars, file=file)           

    if section == "fit":
        DA = self._fit_dict
        _print_fit_pars = f"""# ============ FIT setup ====================================================================================="""+\
        f"""\n{'Total_no_steps':23s}  {DA['n_steps']*DA['n_chains']} \n{'Number_chains':23s}  {DA['n_chains']} \n{'Number_of_processes':23s}  {DA['n_cpus']} """+\
            f"""\n{'Burnin_length':23s}  {DA['n_burn']} \n{'n_live':23s}  {DA['n_live']} \n{'d_logz':23s}  {DA['dyn_dlogz']} \n{'Sampler':23s}  {DA['sampler']} \n{'emcee_move':23s}  {DA['emcee_move']} """+\
                    f"""\n{'leastsq_for_basepar':23s}  {DA['leastsq_for_basepar']} """+\
                        f"""\n{'apply_LCjitter':23s}  {DA['apply_LCjitter']} \n{'apply_RVjitter':23s}  {DA['apply_RVjitter']} """+\
                        f"""\n{'LCbasecoeff_lims':23s}  {DA['LCbasecoeff_lims']} \n{'RVbasecoeff_lims':23s}  {DA['RVbasecoeff_lims']} """
        
        print(_print_fit_pars, file=file)

    if section == "rv_baseline":
        _print_rv_baseline = """# ============ Input RV curves, baseline function, GP, spline,  gamma ============================================ """+\
                                f"""\n{'name':{max_name_len}s} {"scl_col":7s} |{'col0':4s} {'col3':4s} {'col4':4s} {"col5":4s}| {'sin':3s} {"GP":2s} {"spline_config  ":15s} | {f'gamma_{self._RVunit}':9s}"""
        if self._names != []:
            DA = self._rvdict
            txtfmt = f"\n{{0:{max_name_len}s}}"+" {1:7s} |{2:4d} {3:4d} {4:4d} {5:4d}| {6:3d} {7:2s} {8:15s} | {9} "         
            for i in range(self._nRV):
                gam_pri_ = f'N({DA["gammas"][i]},{DA["sig_lo"][i]})' if DA["sig_lo"][i] else f'U({DA["bound_lo"][i]},{DA["gammas"][i]},{DA["bound_hi"][i]})' if DA["bound_hi"][i] else f"F({DA['gammas'][i]})"
                t = txtfmt.format(self._names[i],self._rescaled_data.config, *self._RVbases[i],
                                    self._useGPrv[i],self._rvspline[i].conf,gam_pri_)
                _print_rv_baseline += t
        print(_print_rv_baseline, file=file)

    if section == "rv_gp":
        DA = self._rvGP_dict
        _print_gp = f"""# ==================== RV GP properties ========================================================================== """+\
                     f"""\n{"name":{max_name_len}s} {'par1':4s} {"kern1":5s} {'Amplitude1':18s} {'length_scale':15s} |{'op':2s}| {'par2':4s} {"kern2":5s} {'Amplitude2':18s} {'length_scale2':15s}"""
        if DA != {}: 
            #define gp print out format
            txtfmt = f"\n{{0:{max_name_len}s}}"+" {1:4s} {2:5s} {3:18s} {4:15s} |{5:2s}| {6:4s} {7:5s} {8:18s} {9:15s} "        

            for lc in DA.keys():
                ngp = DA[lc]["ngp"]
                prior={}
                for p in ["amplitude", "lengthscale"]:
                    for j in range(ngp):
                        if DA[lc][p+str(j)].to_fit == "n":
                            prior[p+str(j)] = f"F({DA[lc][p+str(j)].start_value})"
                        elif DA[lc][p+str(j)].to_fit == "y" and DA[lc][p+str(j)].prior == "n":
                            b_lo = 0 if DA[lc][p+str(j)].bounds_lo==1e-20 else DA[lc][p+str(j)].bounds_lo
                            prior[p+str(j)] = f"LU({b_lo},{DA[lc][p+str(j)].start_value},{DA[lc][p+str(j)].bounds_hi})"
                        elif DA[lc][p+str(j)].to_fit == "y" and DA[lc][p+str(j)].prior == "p":
                            prior[p+str(j)] = f"N({DA[lc][p+str(j)].prior_mean},{DA[lc][p+str(j)].prior_width_lo})"

                if ngp == 2:
                    t = txtfmt.format(lc,DA[lc]["amplitude0"].user_data[1], DA[lc]["amplitude0"].user_data[0],  
                                                    prior["amplitude0"], prior["lengthscale0"], DA[lc]["op"], 
                                        DA[lc]["amplitude1"].user_data[1], DA[lc]["amplitude1"].user_data[0],
                                                    prior["amplitude1"], prior["lengthscale1"])
                else:
                    t = txtfmt.format(lc,DA[lc]["amplitude0"].user_data[1], DA[lc]["amplitude0"].user_data[0],  
                                                    prior["amplitude0"], prior["lengthscale0"], "--", 
                                        "None", "None", "None", "None")

                _print_gp += t
        print(_print_gp, file=file)

class _param_obj():
    def __init__(self,to_fit,start_value,step_size,
                    prior, prior_mean, prior_width_lo, prior_width_hi,
                    bounds_lo, bounds_hi,user_data=None):
        """  
        Parameters:
        -----------
        to_fit : str;
            'y' or 'n' to fit or not fit the parameter.
        start_value : float;
            starting value for the parameter.
        step_size : float;
            step size for the parameter.
        prior : str;
            'n' or 'p' to not use (n) or use (p) a normal prior.
        prior_mean : float;
            mean of the normal prior.
        prior_width_lo : float;
            lower sigma of the normal prior.
        prior_width_hi : float;
            upper sigma of the normal prior.
        bounds_lo : float;
            lower bound for the parameter.
        bounds_hi : float;
            upper bound for the parameter.
        user_data : any;
            any data to be stored in the parameter object.

        Returns:
        --------
        param_obj : object;
            object with the parameters.
        """
    
        self.to_fit         = to_fit if (to_fit in ["n","y"]) else _raise(ValueError, "to_fit (to_fit) must be 'n' or 'y'")
        self.start_value    = start_value
        self.step_size      = step_size
        self.prior          = prior if (prior in ["n","p"]) else _raise(ValueError, "prior (prior) must be 'n' or 'p'")
        self.prior_mean     = prior_mean
        self.prior_width_lo = prior_width_lo
        self.prior_width_hi = prior_width_hi
        self.bounds_lo      = bounds_lo
        self.bounds_hi      = bounds_hi
        self.user_data      = user_data
        
    def _set(self, par_list):
        return self.__init__(*par_list)
    
    def __repr__(self):
        return f"{self.__dict__}"
    
    def _get_list(self):
        return [p for p in self.__dict__.values()]

class _text_format:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'

filter_shortcuts = dict(kepler='Kepler/Kepler.k',
                    tess='TESS/TESS.Red',
                    cheops='CHEOPS/CHEOPS.band',
                    wfc3_g141='HST/WFC3_IR.G141',
                    wfc3_g102='HST/WFC3_IR.G102',
                    sp36='Spitzer/IRAC.I1',
                    sp45='Spitzer/IRAC.I2',
                    ug='Geneva/Geneva.U',
                    b1='Geneva/Geneva.B1',
                    b2='Geneva/Geneva.B2',
                    bg='Geneva/Geneva.B',
                    gg='Geneva/Geneva.G',
                    v1='Geneva/Geneva.V2',
                    vg='Geneva/Geneva.V',
                    sdss_g='SLOAN/SDSS.g',
                    sdss_r='SLOAN/SDSS.r',
                    sdss_i='SLOAN/SDSS.i',
                    sdss_z='SLOAN/SDSS.z')

#========================================================================
class load_lightcurves:
    """
        lightcurve object to hold lightcurves for analysis
        
        Parameters:
        -----------
        data_filepath : str;
            Filepath where lightcurves files are located. Default is None which implies the data is in the current working directory.

            
        file_list : list;
            List of filenames for the lightcurves. Files must have 9 columns: time,flux,err,xc,xc,xc,xc,xc,xc. 
            where xc are columns that can be used in decorrelating the flux. Arrays of zeroes are put in xc if file contains less than 9 columns.
            
        filter : list, str, None;
            filter for each lightcurve in file_list. if a str is given, it is used for all lightcurves,
            if None, the default of "V" is used for all.
            
        lamdas : list, int, float, None;
            central wavelength in microns for each lightcurve in file_list. if a int or float is given, it is used for all lightcurves,
            if None, the default of 0.6 is used for all.
        
        Returns:
        --------
        lc_obj : light curve object

        Example:
        --------
        >>> lc_obj = load_lightcurves(file_list=["lc1.dat","lc2.dat"], filters=["V","I"], lamdas=[6000,8000])
        
    """
    def __init__(self, file_list=None, data_filepath=None, filters=None, lamdas=None, nplanet=1,
                    verbose=True, show_guide=False):
        self._obj_type = "lc_obj"
        self._nplanet  = nplanet
        self._fpath = os.getcwd()+'/' if data_filepath is None else data_filepath
        self._names = [file_list] if isinstance(file_list, str) else [] if file_list is None else file_list
        for lc in self._names: assert os.path.exists(self._fpath+lc), f"file {lc} does not exist in the path {self._fpath}."
        
        assert filters is None or isinstance(filters, (list, str)), \
            f"filters is of type {type(filters)}, it should be a list, a string or None."
        assert lamdas  is None or isinstance(lamdas, (list, int, float)), \
            f"lamdas is of type {type(lamdas)}, it should be a list, int or float."
        
        if isinstance(filters, str): filters = [filters]
        if isinstance(lamdas, (int, float)): lamdas = [float(lamdas)]

        self._nphot = len(self._names)
        if filters is not None and len(filters) == 1: filters = filters*self._nphot
        if lamdas is  not None and len(lamdas)  == 1: lamdas  = lamdas *self._nphot

        self._filters = ["V"]*self._nphot if filters is None else [f for f in filters]
        self._lamdas  = [0.6]*self._nphot if lamdas is None else [l for l in lamdas]
        self._filter_shortcuts = filter_shortcuts
        
        assert self._nphot == len(self._filters) == len(self._lamdas), \
            f"filters and lamdas must be a list with same length as file_list (={self._nphot})"
        self._filnames   = np.array(list(sorted(set(self._filters),key=self._filters.index)))

        #modify input files to have 9 columns as CONAN expects then save as attribute of self
        self._input_lc = {}     #dictionary to hold input lightcurves
        for f in self._names:
            fdata = np.loadtxt(self._fpath+f)
            nrow,ncol = fdata.shape
            if ncol < 9:
                print(f"writing ones to the missing columns of file: {f}")
                new_cols = np.ones((nrow,9-ncol))
                fdata = np.hstack((fdata,new_cols))
                np.savetxt(self._fpath+f,fdata,fmt='%.8f')
            #store input files in lc object
            self._input_lc[f] = {}
            for i in range(9): self._input_lc[f][f"col{i}"] = fdata[:,i]
        
        #list to hold initial baseline model coefficients for each lc
        self._bases_init =  [dict(off=1, A0=0, B0= 0, C0=0, D0=0,A3=0, B3=0, A4=0, B4=0,
                                    A5=0, B5=0, A6=0, B6=0,A7=0, B7=0, amp=0,freq=0,phi=0,ACNM=1,BCNM=0) 
                                for _ in range(self._nphot)]

        self._show_guide = show_guide
        self._clipped_data  = SimpleNamespace(flag=False, config=["None"]*self._nphot)
        self._rescaled_data = SimpleNamespace(flag=False, config="None")
        self.lc_baseline(re_init = hasattr(self,"_bases"), verbose=False)   

        if self._show_guide: print("\nNext: use method `lc_baseline` to define baseline model for each lc or method " + \
            "`get_decorr` to obtain best best baseline model parameters according bayes factor comparison")

    def rescale_data_columns(self,method="med_sub", verbose=True):

        """
            Function to rescale the data columns of the lightcurves. This can be important when decorrelating the data with polynomials.
            The operation is not performed on columns 0,1,2. It is only performed on columns whose values do not span zero.
            Function can only be run once on the loaded datasets but can be reset by running `load_lightcurves()` again. 

            The method can be one of ["med_sub", "rs0to1", "rs-1to1"] which subtracts the median, rescales t0 [0-1], or rescales to [-1,1] respectively.
            The default is "med_sub" which subtracts the median from each column.
        """
        assert method in ["med_sub", "rs0to1", "rs-1to1"], f"method must be one of 'med_sub', 'rs0to1', 'rs-1to1' not {method}"
        
        if self._rescaled_data.flag:
            print("Data columns have already been rescaled. run `load_lightcurves()` again to reset.")
            return None
        
        for lc in self._names:
            if verbose: print(f"Rescaling data columns of {lc}...")
            for i in range(9):
                if i not in [0,1,2]:
                    if not (min(self._input_lc[lc][f"col{i}"]) <= 0 <=  max(self._input_lc[lc][f"col{i}"])):     #if zero not in array
                        if method == "med_sub":
                            self._input_lc[lc][f"col{i}"] -= np.median(self._input_lc[lc][f"col{i}"])
                        elif method == "rs0to1":
                            self._input_lc[lc][f"col{i}"] = rescale0_1(self._input_lc[lc][f"col{i}"])
                        elif method == "rs-1to1":
                            self._input_lc[lc][f"col{i}"] = rescale_minus1_1(self._input_lc[lc][f"col{i}"])

        self._rescaled_data = SimpleNamespace(flag=True, config=method)

    def get_decorr(self, T_0=None, Period=None, rho_star=None, D_occ=0, Impact_para=0, RpRs=1e-5,
                    Eccentricity=0, omega=90, A_pc=0, ph_off=0, K=0, q1=0, q2=0, 
                    mask=False, spline=None,ss_exp =None,delta_BIC=-5, decorr_bound =(-1,1),
                    exclude_cols=[], enforce_pars=[],verbose=True, 
                    show_steps=False, plot_model=True, use_result=True):
        """
            Function to obtain best decorrelation parameters for each light-curve file using the forward selection method.
            It compares a model with only an offset to a polynomial model constructed with the other columns of the data.
            It uses columns 0,3,4,5,6,7 to construct the polynomial trend model. The temporary decorr parameters are labelled Ai,Bi for 1st & 2nd order coefficients in column i.
            A spline can also be included to decorrelate against any column.
            
            Decorrelation parameters that reduce the BIC by 5(i.e delta_BIC = -5) are iteratively selected. This implies bayes_factor=exp(-0.5*-5) = 12 or more is required for a parameter to be selected.
            The result can then be used to populate the `lc_baseline` method, if use_result is set to True. The transit, limb darkening and phase curve parameters can also be setup from the inputs to this function.

            Parameters:
            -----------
            T_0, Period, rho_star, D_occ, Impact_para, RpRs, Eccentricity, omega, A_pc, ph_off: floats,tuple, None;
                transit/eclipse parameters of the planet. T_0 and Period must be in same units as the time axis (col0) in the data file.
                if float/int, the values are held fixed. if tuple/list of len 2 implies gaussian prior as (mean,std) while len 3 implies [min,start_val,max].
                
            q1,q2 : float,tuple, list  (optional);
                Kipping quadratic limb darkening parameters. if float, the values are held fixed. if tuple/list of len 2 implies gaussian prior as (mean,std) while len 3 implies [min,start_val,max].
                give list of values for assign value to each unique filter in the data, or one value to be used for all filtets. Default is 0 for all filters.
    
            delta_BIC : float (negative);
                BIC improvement a parameter needs to provide in order to be considered relevant for decorrelation. + \
                    Default is conservative and set to -5 i.e, parameters needs to lower the BIC by 5 to be included as decorrelation parameter.

            mask : bool ;
                If True, transits and eclipses are masked using T_0, P and rho_star (duration).
        
            decorr_bound: tuple of size 2;
                bounds when fitting decorrelation parameters. Default is (-1,1)

            spline : list of dict;
                spline configuration to use in decorrelation an axis of the data. Default is None which implies no spline is used.
                the config is given as a dict with keys "col", "knot_spacing", "degree" specifying the column, the knot spacing and the degree of the spline.
                e.g. spline = {"col":0, "knot_spacing":0.1, "degree":3} will fit a spline the flux as a function ofcolumn 0 with knot spacing of 0.1 and degree 3.

            ss_exp : list, None;
               exposure time of the lcs to configure supersampline. Default is None which implies no supersampling.

            exclude_cols : list of int;
                list of column numbers (e.g. [3,4]) to exclude from decorrelation. Default is [].

            enforce_pars : list of int;
                list of decorr params (e.g. ['B3', 'A5']) to enforce in decorrelation. Default is [].

            verbose : Bool, optional;
                Whether to show the table of baseline model obtained. Defaults to True.

            show_steps : Bool, optional;
                Whether to show the steps of the forward selection of decorr parameters. Default is False
            
            plot_model : Bool, optional;
                Whether to overplot suggested trend model on the data. Defaults to True.

            use_result : Bool, optional;
                whether to use result/input to setup the baseline model and transit/eclipse models. Default is True.
        
            Returns
            -------
            decorr_result: list of result object
                list containing result object for each lc.
        """
        assert isinstance(exclude_cols, list), f"get_decorr(): exclude_cols must be a list of column numbers to exclude from decorrelation but {exclude_cols} given."
        for c in exclude_cols: assert isinstance(c, int), f"get_decorr(): column number to exclude from decorrelation must be an integer but {c} given in exclude_cols."

        nfilt = len(self._filnames)
        if isinstance(q1, np.ndarray): q1 = list(q1)
        if isinstance(q1, list): assert len(q1) == nfilt, f"get_decorr(): q1 must be a list of same length as number of unique filters {nfilt} but {len(q1)} given." 
        else: q1=[q1]*nfilt
        if isinstance(q2, np.ndarray): q2 = list(q2)
        if isinstance(q2, list): assert len(q2) == nfilt, f"get_decorr(): q2 must be a list of same length as number of unique filters {nfilt} but {len(q2)} given." 
        else: q2=[q2]*nfilt

        blpars = {"dcol0":[], "dcol3":[],"dcol4":[], "dcol5":[], "dcol6":[], "dcol7":[],"gp":[]}  #inputs to lc_baseline method
        self._decorr_result = []   #list of decorr result for each lc.

        input_pars = dict(T_0=T_0, Period=Period, rho_star=rho_star, Impact_para=Impact_para, \
                            RpRs=RpRs, Eccentricity=Eccentricity, omega=omega, K=K)

        self._tra_occ_pars = dict(T_0=T_0, Period=Period, rho_star=rho_star, D_occ=D_occ, Impact_para=Impact_para, \
                                    RpRs=RpRs, Eccentricity=Eccentricity, omega=omega, A_pc=A_pc, ph_off=ph_off,) #transit/occultation parameters
        
        for p in self._tra_occ_pars:
            if p not in ["rho_star","A_pc","ph_off","D_occ"]:
                if isinstance(self._tra_occ_pars[p], (int,float,tuple)): self._tra_occ_pars[p] = [self._tra_occ_pars[p]]*self._nplanet
                if isinstance(self._tra_occ_pars[p], (list)): assert len(self._tra_occ_pars[p]) == self._nplanet, \
                    f"get_decorr(): {p} must be a list of same length as number of planets {self._nplanet} but {len(self._tra_occ_pars[p])} given."
            else:
                assert isinstance(self._tra_occ_pars[p],(int,float,tuple)),f"get_decorr(): {p} must be one of int/float/tuple but {self._tra_occ_pars[p]} given "

        ld_q1, ld_q2 = {},{}
        for i,fil in enumerate(self._filnames):
            ld_q1[fil] = q1[i]
            ld_q2[fil] = q2[i]
        
        assert delta_BIC<0,f'get_decorr(): delta_BIC must be negative for parameters to provide improved fit but {delta_BIC} given.'
        
        #check spline input
        if spline is None: spline = [None]*self._nphot
        elif isinstance(spline, dict): spline = [spline]*self._nphot
        elif isinstance(spline, list): 
            if len(spline) == 1: spline = spline*self._nphot
            assert len(spline) == self._nphot,f"get_decorr(): list given for spline must have same length as number of input lcs but {len(spline)} given."
        else: _raise(TypeError, f"get_decorr(): `spline` must be dict or list of dict with same length as number of input files but {type(spline)} given.")

        for sp in spline:
            if isinstance(sp, dict): 
                assert "col" in sp.keys(), f"get_decorr(): spline dict must have key 'col' "
                assert "knot_spacing" in sp.keys(), f"get_decorr(): spline dict must have key 'knot_spacing' "
                assert "degree" in sp.keys(), f"get_decorr(): spline dict must have key 'degree' "
            elif sp is None: pass
            else: _raise(TypeError, f"get_decorr(): all elements in spline list must be dict or None but {sp} given")

        #check supersampling input
        if ss_exp is None: ss_exp = [None]*self._nphot
        elif isinstance(ss_exp, (int,float)): ss_exp = [ss_exp]*self._nphot
        elif isinstance(ss_exp, list): 
            if len(ss_exp) == 1: ss_exp= ss_exp*self._nphot
            assert len(ss_exp) == self._nphot,f"get_decorr(): list given for spline must have same length as number of input lcs but {len(spline)} given."
        else: _raise(TypeError, f"get_decorr(): `spline` must be dict or list of dict with same length as number of input files but {type(spline)} given.")


        self._tmodel = []  #list to hold determined trendmodel for each lc
        decorr_cols = [0,3,4,5,6,7]
        for c in exclude_cols: assert c in decorr_cols, f"get_decorr(): column number to exclude from decorrelation must be in {decorr_cols} but {c} given in exclude_cols." 
        _ = [decorr_cols.remove(c) for c in exclude_cols]  #remove excluded columns from decorr_cols

        for j,file in enumerate(self._names):
            df = self._input_lc[file]
            if verbose: print(_text_format.BOLD + f"\ngetting decorrelation parameters for lc: {file} (spline={spline[j] is not None},s_samp={ss_exp[j] is not None})" + _text_format.END)
            all_par = [f"{L}{i}" for i in decorr_cols for L in ["A","B"]] 

            out = _decorr(df, **self._tra_occ_pars, q1=ld_q1[self._filters[j]],q2=ld_q2[self._filters[j]], mask=mask,
                            offset=0, decorr_bound=decorr_bound,spline=spline[j],ss_exp=ss_exp[j], npl=self._nplanet)    #no trend, only offset
            best_bic  = out.bic
            best_pars = {"offset":0} if spline[j] is None else {}          #parameter always included
            for cp in enforce_pars: best_pars[cp]=0                             #add enforced parameters
            _ = [all_par.remove(cp) for cp in enforce_pars if cp in all_par]    #remove enforced parameters from all_par to test

            if show_steps: print(f"{'Param':7s} : {'BIC':6s} N_pars \n---------------------------")

            del_BIC = -np.inf # bic_ratio = 0 # bf = np.inf
            while del_BIC < delta_BIC:#while  bf > 1:
                if show_steps: print(f"{'Best':7s} : {best_bic:.2f} {len(best_pars.keys())} {list(best_pars.keys())}\n---------------------")
                pars_bic = {}
                for p in all_par:
                    dtmp = best_pars.copy()   #always include offset
                    dtmp[p] = 0
                    out = _decorr(self._input_lc[file], **self._tra_occ_pars, q1=ld_q1[self._filters[j]],q2=ld_q2[self._filters[j]],**dtmp,
                                    decorr_bound=decorr_bound,spline=spline[j],ss_exp=ss_exp[j], npl=self._nplanet)
                    if show_steps: print(f"{p:7s} : {out.bic:.2f} {out.nvarys}")
                    pars_bic[p] = out.bic

                par_in = min(pars_bic,key=pars_bic.get)   #parameter that gives lowest BIC
                par_in_bic = pars_bic[par_in]
                del_BIC = par_in_bic - best_bic
                bf = np.exp(-0.5*(del_BIC))
                if show_steps: print(f"+{par_in} -> BF:{bf:.2f}, del_BIC:{del_BIC:.2f}")

                if del_BIC < delta_BIC:# if bf>1:
                    if show_steps: print(f"adding {par_in} lowers BIC to {par_in_bic:.2f}\n" )
                    best_pars[par_in]=0
                    best_bic = par_in_bic
                    all_par.remove(par_in)            

            result = _decorr(df, **self._tra_occ_pars, q1=ld_q1[self._filters[j]],q2=ld_q2[self._filters[j]],
                                **best_pars, decorr_bound=decorr_bound,spline=spline[j],ss_exp=ss_exp[j], npl=self._nplanet)

            self._decorr_result.append(result)
            print(f"BEST BIC:{result.bic:.2f}, pars:{list(best_pars.keys())}")
            
            #calculate determined trend and tra/occ model over all data(no mask)
            pps = result.params.valuesdict()
            #convert result transit parameters to back to a list
            for p in ['RpRs', 'Impact_para', 'T_0', 'Period', 'Eccentricity', 'omega']:
                if self._nplanet==1:
                    pps[p] = [pps[p]]  
                else:      
                    pps[p] = [pps[p+f"_{n}"] for n in range(1,self._nplanet+1)]
                    _ = [pps.pop(f"{p}_{n}") for n in range(1,self._nplanet+1)]
    
            self._tmodel.append(_decorr(df,**pps, spline=spline[j],ss_exp=ss_exp[j],npl=self._nplanet, return_models=True))

            #set-up lc_baseline model from obtained configuration
            blpars["dcol0"].append( 2 if pps["B0"]!=0 else 1 if  pps["A0"]!=0 else 0)
            blpars["dcol3"].append( 2 if pps["B3"]!=0 else 1 if  pps["A3"]!=0 else 0)
            blpars["dcol4"].append( 2 if pps["B4"]!=0 else 1 if  pps["A4"]!=0 else 0)
            blpars["dcol5"].append( 2 if pps["B5"]!=0 else 1 if  pps["A5"]!=0 else 0)
            blpars["dcol6"].append( 2 if pps["B6"]!=0 else 1 if  pps["A6"]!=0 else 0)
            blpars["dcol7"].append( 2 if pps["B7"]!=0 else 1 if  pps["A7"]!=0 else 0)
            blpars["gp"].append("n")
            # store baseline model coefficients for each lc, to used as start values of mcmc
            self._bases_init[j] = dict(off=1+pps["offset"], 
                                            A0=pps["A0"], B0=pps["B0"], C0=0, D0=0,
                                            A3=pps["A3"], B3=pps["B3"], 
                                            A4=pps["A4"], B4=pps["B4"],
                                            A5=pps["A5"], B5=pps["B5"], 
                                            A6=pps["A6"], B6=pps["B6"],
                                            A7=pps["A7"], B7=pps["B7"], 
                                            amp=0,freq=0,phi=0,ACNM=1,BCNM=0)

        if plot_model:
            _plot_data(self,plot_cols=(0,1,2),col_labels=("time","flux"),model_overplot=self._tmodel)

        #prefill other light curve setup from the results here or inputs given here.
        if use_result:
            # spline
            if spline != [None]*self._nphot: 
                print(_text_format.BOLD + f"\nSetting-up spline for decorrelation."+ _text_format.END +\
                        " Use `.add_spline(None)` method to remove/modify")
                spl_lcs,spl_par,spl_knots,spl_deg = [],[],[],[]
                for j,file in enumerate(self._names):
                    if spline[j] is not None: 
                        spl_lcs.append(file)
                        spl_par.append(f"col{spline[j]['col']}")
                        spl_knots.append(spline[j]['knot_spacing'])
                        spl_deg.append(spline[j]['degree'])
                self.add_spline(lc_list=spl_lcs, par = spl_par, knot_spacing=spl_knots, degree=spl_deg,verbose=False)
            
            # supersampling
            if ss_exp != [None]*self._nphot:
                print(_text_format.BOLD + f"\nSetting-up supersampling."+ _text_format.END + " Use `.supersample(None)` method to remove/modify")
                ss_lcs,ss_exp_list = [],[]
                for j,file in enumerate(self._names):
                    if ss_exp[j] is not None: 
                        ss_lcs.append(file)
                        ss_exp_list.append(ss_exp[j])
                self.supersample(lc_list=ss_lcs, exp_time = ss_exp_list,verbose=False)

            # baseline
            if verbose: print(_text_format.BOLD + "\nSetting-up baseline model from result" +_text_format.END)
            self.lc_baseline(**blpars, verbose=verbose)
            print(_text_format.RED + f"\n Note: GP flag for the lcs has been set to {self._useGPphot}. "+\
                    "Use `._useGPphot` attribute to modify this list with 'y','ce' or 'n' for each loaded lc\n" + _text_format.END)

            # transit/RV
            if verbose: print(_text_format.BOLD + "\nSetting-up transit pars from input values" +_text_format.END)
            self.planet_parameters(**input_pars, verbose=verbose)

            # phasecurve
            if np.any([self._tra_occ_pars["D_occ"],self._tra_occ_pars["A_pc"],self._tra_occ_pars["ph_off"]] != 0): 
                if verbose: print(_text_format.BOLD + "\nSetting-up Phasecurve pars from input values" +_text_format.END)
                self.setup_phasecurve(D_occ=self._tra_occ_pars["D_occ"], A_pc=self._tra_occ_pars["A_pc"],
                                        ph_off=self._tra_occ_pars["ph_off"], verbose=verbose)
            else:
                self.setup_phasecurve(verbose=False)
            
            # limb darkening
            if verbose: print(_text_format.BOLD + "\nSetting-up Limb darkening pars from input values" +_text_format.END)
            self.limb_darkening(q1=q1, q2=q2, verbose=verbose)


        return self._decorr_result
    
    
    def clip_outliers(self, lc_list="all", clip=5, width=15, show_plot=True, verbose=True):

        """
        Remove outliers using a running median method. Points > clip*M.A.D are removed
        where M.A.D is the mean absolute deviation from the median in each window

        Parameters:
        ------------
        lc_list: list of string, None, 'all';
            list of lightcurve filenames on which perform outlier clipping. Default is 'all' which clips all lightcurves in the object.
        
        clip: int/float,list;
            cut off value above the median. Default is 5

        width: int,list;
            Number of points in window to use when computing the running median. Must be odd. Default is 15

        show_plot: bool;
            set True to plot the data and show clipped points.
        
        verbose: bool;
            Prints number of points that have been cut. Default is True

        """
        if self._clipped_data.flag:
            print("Data has already been clipped. run `load_lightcurves()` again to reset.")
            return None

        if lc_list == None: 
            print("lc_list is None: No lightcurve to clip outliers.")
            return None
        if isinstance(lc_list, str) and (lc_list != 'all'): lc_list = [lc_list]
        if lc_list == "all": lc_list = self._names

        if isinstance(width, int): width = [width]*len(lc_list)
        elif isinstance(width, list): 
            if len(width)==1: width = width*len(lc_list)
        else: _raise(TypeError, f"clip_outliers(): width must be an int or list of int but {clip} given.")
            
        if isinstance(clip, int): clip = [clip]*len(lc_list)
        elif isinstance(clip, list): 
            if len(clip)==1: clip = clip*len(lc_list)
        else: _raise(TypeError, f"clip_outliers(): width must be an int or list of int but {clip} given.")
            
            
        assert len(width) == len(clip) == len(lc_list), f"clip_outliers(): width, clip and lc_list must have same length but {len(width)}, {len(clip)} and {len(lc_list)} given."

        conf=[]
        for i,file in enumerate(lc_list):
            assert file in self._names, f"clip_outliers(): filename {file} not in loaded lightcurves."

            if width[i]%2 == 0: width[i] += 1   #if width is even, make it odd
            conf.append(f"W{width[i]}C{clip[i]}")

            thisLCdata = self._input_lc[file]#  np.loadtxt(self._fpath+file)

            _,_,clpd_mask = outlier_clipping(x=thisLCdata["col0"],y=thisLCdata["col1"],clip=clip[i],width=width[i],
                                                verbose=False, return_clipped_indices=True)   #returns mask of the clipped points
            ok = ~clpd_mask     #invert mask to get indices of points that are not clipped
            if verbose: print(f'\n{file}: Rejected {sum(~ok)} points more than {clip[i]:0.1f} x MAD from the median')

            if show_plot:
                fig = plt.figure(figsize=(15,3))
                plt.title(file)
                plt.plot(thisLCdata["col0"][ok], thisLCdata["col1"][ok], '.b')
                plt.plot(thisLCdata["col0"][~ok], thisLCdata["col1"][~ok], '.r')
                plt.show()

            #replace all columns of input file with the clipped data
            self._input_lc[file] = {k:v[ok] for k,v in thisLCdata.items()}

        self._clipped_data = SimpleNamespace(flag=True, width=width, clip=clip, lc_list=lc_list, config=conf)

    
    def split_transits(self, filename=None, P=None, t_ref=None, baseline_amount=0.3, input_t0s=None, show_plot=True, save_separate=True, same_filter=True):
    
        """
        Function to split the transits in the data into individual transits and save them in separate files or to remove a certain amount of data points around the transits while keeping them in the original file.
        Recommended to set show_plot=True to visually ensure that transits are well separated.

        Parameters:
        -----------

        filename: string;
                name of the lightcurve file to clip. Default is None

        P : float;
            Orbital period in same unit as t.

        t_ref : float;
            reference time of transit - T0 from literature or visual estimate of a mid-transit time in the data 
            Used to calculate expected time of transits in the data assuming linear ephemerides.

        baseline_amount: float between 0.05 and 0.5 times the period P;
            amount of baseline data to keep before and after each transit. Default is 0.3*P, has to be between 0.05P and 0.5P.
            
        input_t0s: array, list, (optional);
            split transit using these mid-transit times
            
        show_plot: bool;
            set true to plot the data and show split points.
            
        save_separate: bool;
            set True to separately save each transit and its baseline_amount around it in a new file. Default is True.

        same_filter: bool; 
            set True to save the split transits in the same filter as the original file. Default is True.
        """

        if filename==None: 
            print("No lightcurve filename given.")
            return None
        assert filename in self._names, f"split_transits(): filename {filename} not in loaded lightcurves."
        
        data = np.loadtxt(self._fpath+filename)
        # data = self._input_lc[filename]
        #TODO allow to split data at any given points or with user defined gap size
        
        t = data.transpose()[0]
        flux = data.transpose()[1]
        
        if baseline_amount < 0.05 :
            baseline_amount = 0.05
            print("Baseline amount defaulted to minimum 0.05")
        elif baseline_amount > 0.5 :
            baseline_amount = 0.5
            print("Baseline amount defaulted to maximum 0.5")
            
        
        if input_t0s is not None:
            t0s = list(input_t0s)

        else:
            tref = t_ref
            if t_ref < t.min() or t.max() < t_ref:        #if reference time t0 is not within this timeseries
                #find transit time that falls around middle of the data
                ntrans = int((np.median(t) - tref)/P)   
                tref = t_ref + ntrans*P

            nt = int( (tref-t.min())/P )                            #how many transits behind tref is the first transit
            tr_first = tref - nt*P                                    #time of first transit in data
            tr_last = tr_first + int((t.max() - tr_first)/P)*P        #time of last transit in data

            n_tot_tr = int((tr_last - tr_first)/P)                  #total nmumber of transits in data_range
            t0s = [tr_first + P*n for n in range(n_tot_tr+1) ]        #expected tmid of transits in data (if no TTV)
            #remove tmid without sufficient transit data around it
            t0s = list(filter(lambda t0: ( t[ (t<t0+0.1*P) & (t>t0-0.1*P)] ).size>0, t0s))


        #split data into individual transits. taking points around each tmid    
        tr_times= []
        fluxes= []
        indz = []
        for i in range(len(t0s)):
            higher_than = t>(t0s[i]-baseline_amount*P)
            lower_than = t<(t0s[i]+baseline_amount*P)
            if i==0: 
                tr_times.append(t[higher_than & lower_than])
                indz.append( np.argwhere(higher_than & lower_than).reshape(-1) )
            elif i == len(t0s)-1: 
                tr_times.append(t[higher_than & lower_than])
                indz.append( np.argwhere(higher_than & lower_than).reshape(-1) )
            else: 
                tr_times.append(t[higher_than & lower_than])
                indz.append( np.argwhere(higher_than & lower_than).reshape(-1))
            fluxes.append(flux[indz[i]])
            
        tr_edges = [(tr_t[0], tr_t[-1]) for tr_t in tr_times]    #take last time in each timebin as breakpts
        
        tr_times = np.concatenate(tr_times)
        fluxes = np.concatenate(fluxes)
            
        if show_plot:
            assert fluxes is not None, f"plotting requires input flux"
            plt.figure(figsize=(15,3))
            plt.plot(tr_times,fluxes,".")
            for edg in tr_edges:
                plt.axvline(edg[0], ls="dashed", c="k", alpha=0.3)
                plt.axvline(edg[1], ls="dashed", c="k", alpha=0.3)
            plt.plot(t0s, (0.997*np.min(flux))*np.ones_like(t0s),"k^")
            plt.xlabel("Time (days)", fontsize=14)
            plt.title("Using t_ref: dashed vertical lines = transit splitting times;  triangles = identified transits");

        if save_separate:
            #replace filter names
            _flt = self._filters[self._names.index(filename)]
            _lbd = self._lamdas[self._names.index(filename)]
            self._filters.remove(_flt)
            self._lamdas.remove(_lbd)
            self._names.remove(filename)

            for i in range(len(t0s)):
                
                tr_data = data[indz[i]]
                
                tr_filename = os.path.splitext(filename)
                tr_filename = tr_filename[0] + "_tr" + str(i) + tr_filename[1]
            
                np.savetxt(self._fpath+tr_filename,tr_data,fmt='%.8f')
                print("Saved " + self._fpath + tr_filename)

                self._names.append(tr_filename)
                if same_filter: self._filters.append(_flt)
                else: self._filters.append(_flt+str(i))
                # self._filnames   = np.array(list(sorted(set(self._filters),key=self._filters.index)))

                self._lamdas.append(_lbd)
        # self.lc_baseline(re_init=True,verbose=False)
        self.__init__(self._names, self._fpath, self._filters, self._lamdas, self._nplanet)

            
    def lc_baseline(self, dcol0=None, dcol3=None, dcol4=None,  dcol5=None, dcol6=None, 
                    dcol7=None, dsin=None, grp=None, grp_id=None, gp="n", re_init=False,verbose=True):
        """
            Define baseline model parameters to fit for each light curve using the columns of the input data. `dcol0` refers to decorrelation setup for column 0, `dcol3` for column 3 and so on.
            Each baseline decorrelation parameter (dcolx) should be a list of integers specifying the polynomial order for column x for each light curve.
            e.g. Given 3 input light curves, if one wishes to fit a 2nd order trend in column 0 to the first and third lightcurves,
            then `dcol0` = [2, 0, 2].
            The decorrelation parameters depend on the columns (col) of the input light curve. Any desired array can be put in these columns to decorrelate against them. 
            Note that col0 is usually the time array.


            Parameters:
            -----------
            dcol0, dcol3,dcol4,dcol5,dcol6,dcol7 : list of int;
                polynomial order to fit to each column. Default is 0 for all columns.

            grp_id : list (same length as file_list);
                group the different input lightcurves by id so that different transit depths can be fitted for each group.

            gp : list (same length as file_list); 
                list containing 'y', 'n', or 'ce' to specify if a gp will be fitted to a light curve. +\
                    'y' indicates that the george gp package will be used while 'ce' uses the celerite package.
            
            re_init : bool;
                if True, re-initialize all other methods to empty. Default is False.

        """
        DA = locals().copy()     #get a dictionary of the input arguments for easy manipulation
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("re_init")            #remove self from dictionary
        _ = DA.pop("verbose")


        for par in DA.keys():
            if isinstance(DA[par], (int,str)): DA[par] = [DA[par]]*self._nphot      #use same for all lcs
            elif DA[par] is None: DA[par] = ["n"]*self._nphot if par=="gp" else [0]*self._nphot   #no decorr or gp for all lcs
            elif isinstance(DA[par], (list,np.ndarray)):
                if par=="gp": assert len(DA[par]) == self._nphot, f"lc_baseline(): parameter `{par}` must be a list of length {self._nphot} or str (if same is to be used for all LCs) or None."
                else: assert len(DA[par]) == self._nphot, f"lc_baseline(): parameter `{par}` must be a list of length {self._nphot} or int (if same degree is to be used for all LCs) or None (if not used in decorrelation)."

            for p in DA[par]:
                if par=="gp": assert p in ["y","n","ce"], f"lc_baseline(): gp must be a list of 'y', 'n', or 'ce' for each lc but {p} given."
                else: assert isinstance(p, (int,np.int64)) and p<3, f"lc_baseline(): decorrelation parameters must be a list of integers (max int value = 2) but {type(p)} {p} given for {par}."

        DA["grp_id"] = list(np.arange(1,self._nphot+1)) if grp_id is None else grp_id

        self._bases = [ [DA["dcol0"][i], DA["dcol3"][i], DA["dcol4"][i], DA["dcol5"][i],
                        DA["dcol6"][i], DA["dcol7"][i], DA["dsin"][i], 
                        DA["grp"][i]] for i in range(self._nphot) ]

        self._groups    = DA["grp_id"]
        self._grbases   = DA["grp"]    #TODO: never used, remove instances of it
        self._useGPphot = DA["gp"]
        self._gp_lcs    = lambda : np.array(self._names)[np.array(self._useGPphot) != "n"]

        if verbose: _print_output(self,"lc_baseline")
        if np.all(np.array(self._useGPphot) == "n") or self._useGPphot==[]:        #if gp is "n" for all input lightcurves, run add_GP with None
            self.add_GP(None, verbose=False)

        #initialize other methods to empty incase they are not called/have not been called
        if not hasattr(self,"_lcspline") or re_init:      self.add_spline(None, verbose=False)
        if not hasattr(self,"_ss") or re_init:            self.supersample(None, verbose=False)
        if not hasattr(self,"_config_par") or re_init:    self.planet_parameters(verbose=False)
        if not hasattr(self,"_ddfs") or re_init:          self.transit_depth_variation(verbose=False)
        if not hasattr(self,"_PC_dict") or re_init:       self.setup_phasecurve(verbose=False)
        if not hasattr(self,"_contfact_dict") or re_init: self.contamination_factors(verbose=False)
        if not hasattr(self,"_ld_dict") or re_init:       self.limb_darkening(verbose=False)

    def supersample(self, lc_list=None,exp_time=0,verbose=True):
        """
        Supersample long intergration time of lcs in lc_list. This divides each exposure of the lc into  int(exp_time) subexposures to attain ~1min sampling. 
        e.g a lc with 30 minute exp_time will be divided into 30 subexposures of 1 minute each.

        Parameters
        ----------
        lc_list : list, str, optional
            list of lc files to supersample. set to "all" to use supersampling for all lc files. Default is None.

        exp_time : float, tuple, list, optional
            exposure time of each lc to supersample in minutes. if different for each lc in lc_list, give list with exp_time for each lc.
            Default is 0 for no exposure time, which means no supersampling

        verbose : bool, optional
            print output. Default is True.

        Examples
        --------
        To supersample a light curve that has a long cadence of 30mins (0.0208days) to 1 min, 30 points are needed to subdivide each exposure.
        >>> lc_obj.supersample(lc_list="lc1.dat",exp_time=30)
        """
                
        #default supersampling config -- None
        self._ss = [None]*self._nphot
        for i in range(self._nphot):
            self._ss[i] = supersampling()

        if lc_list is None:
            if verbose: print("No supersampling\n")
            return
        elif lc_list == "all":
            lc_list = self._names
        else:
            if isinstance(lc_list, str): lc_list = [lc_list]

        nlc_ss = len(lc_list)   #number of lcs to supersample
        for lc in lc_list:
            assert lc in self._names, f"supersample(): {lc} not in loaded lc files: {self._names}."

        if isinstance(exp_time, (int,float)): exp_time = [exp_time]*nlc_ss
        elif isinstance(exp_time, list): 
            if len(exp_time) == 1: exp_time = exp_time*nlc_ss
            assert len(exp_time)==nlc_ss, f"supersample(): exp_time must be a list of length {nlc_ss} or length 1 (if same is to be used for all lcs)."
        else: _raise(TypeError, f"supersample(): exp_time must be int/float/list but {exp_time} given.")   

        supersample_factor = [int(exp) for exp in exp_time]    #supersample to around 1minute

        for i,lc in enumerate(lc_list):
            ind = self._names.index(lc)  #index of lc in self._names
            self._ss[ind]= supersampling(exp_time=exp_time[i]/(60*24), supersample_factor=supersample_factor[i])

            if verbose: print(f"Supersampling {lc} with exp_time={exp_time[i]:.2f}mins each divided into {supersample_factor[i]} subexposures")
            
        if verbose: _print_output(self,"lc_baseline")

    
    def add_spline(self, lc_list= None, par = None, degree=3, knot_spacing=None,verbose=True):
        """
        add spline to fit correlation along 1 or 2 columns of the data. This splits the data at the defined knots interval and fits a spline to each section. 
        scipy's LSQUnivariateSpline() and LSQBivariateSpline() functions are used for 1D spline and 2D splines respectively.
        All arguments can be given as a list to specify config for each lc file in lc_list.

        Parameters
        ----------
        lc_list : list, str, optional
            list of lc files to fit a spline to. set to "all" to use spline for all lc files. Default is None for no splines.

        par : str,tuple,list, optional
            column of input data to which to fit the spline. must be one/two of ["col0","col3","col4","col5","col6","col7"]. Default is None.
            Give list of columns if different for each lc file. e.g. ["col0","col3"] for spline in col0 for lc1.dat and col3 for lc2.dat. 
            For 2D spline for an lc file, use tuple of length 2. e.g. ("col0","col3") for simultaneous spline fit to col0 and col3.

        degree : int, tuple, list optional
            Degree of the smoothing spline. Must be 1 <= degree <= 5. Default is 3 for a cubic spline.
        
        knot_spacing : float, tuple, list
            distance between knots of the spline. E.g 15 degrees for roll angle in CHEOPS data.
        
        verbose : bool, optional
            print output. Default is True.

        Examples
        --------
        To use different spline configuration for 2 lc files: 2D spline for the first file and 1D for the second.
        >>> lc_obj.add_spline(lc_list=["lc1.dat","lc2.dat"], par=[("col3","col4"),"col4"], degree=[(3,3),2], knot_spacing=[(5,3),2])
        
        For same spline configuration for all loaded lc files
        >>> lc_obj.add_spline(lc_list="all", par="col3", degree=3, knot_spacing=5)
        """  

        #default spline config -- None
        self._lcspline = [None]*self._nphot                   #list to hold spline configuration for each lc
        for i in range(self._nphot):
            self._lcspline[i]        = SimpleNamespace()    #create empty namespace for each lc
            self._lcspline[i].name   = self._names[i]
            self._lcspline[i].dim    = 0
            self._lcspline[i].par    = None
            self._lcspline[i].use    = False
            self._lcspline[i].deg    = None
            self._lcspline[i].knots  = None
            self._lcspline[i].conf   = "None"

        if lc_list is None:
            if verbose: print("No spline\n")
            return
        elif lc_list == "all":
            lc_list = self._names
        else:
            if isinstance(lc_list, str): lc_list = [lc_list]
        
        nlc_spl = len(lc_list)   #number of lcs to add spline to
        for lc in lc_list:
            assert lc in self._names, f"add_spline(): {lc} not in loaded lc files: {self._names}."
        
        DA = locals().copy()

        for p in ["par","degree","knot_spacing"]:
            if DA[p] is None: DA[p] = [None]*nlc_spl
            if isinstance(DA[p], (str,int,float,tuple)): DA[p] = [DA[p]]*nlc_spl
            if isinstance(DA[p], list): assert len(DA[p])==nlc_spl, f"add_spline(): {p} must be a list of length {nlc_spl} or length 1 (if same is to be used for all lcs)."
            
            #check if inputs are valid
            for list_item in DA[p]:
                if p=="par":
                    if isinstance(list_item, str): assert list_item in ["col0","col3","col4","col5","col6","col7",None],f'add_spline(): {p} must be in ["col0","col3","col4","col5"] but {list_item} given.'
                    if isinstance(list_item, tuple): 
                        for tup_item in list_item: assert tup_item in ["col0","col3","col4","col5","col6","col7",None],f'add_spline(): {p} must be in ["col0","col3","col4","col5"] but {tup_item} given.'
                if p=="degree": 
                    assert isinstance(list_item, (int,tuple)),f'add_spline(): {p} must be an integer but {list_item} given.'
                    if isinstance(list_item, tuple):
                        for tup_item in list_item: assert isinstance(tup_item, int),f'add_spline(): {p} must be an integer but {tup_item} given.'

        for i,lc in enumerate(lc_list):
            ind = self._names.index(lc)    #index of lc in self._names
            par, deg, knots =  DA["par"][i], DA["degree"][i], DA["knot_spacing"][i]
            dim = 1 if isinstance(par,str) else len(par)
            assert dim <=2, f"add_spline(): dimension of spline must be 1 or 2 but {par} (dim {dim}) given for {lc}."
            if dim==2:   #if 2d spline 
                if isinstance(deg, int): deg = (deg,deg)  #if degree is int, make it a tuple
                if isinstance(knots, int): knots = (knots,knots)

            self._lcspline[ind].name   = lc
            self._lcspline[ind].dim    = dim
            self._lcspline[ind].par    = par
            self._lcspline[ind].use    = True if par else False
            self._lcspline[ind].deg    = deg
            self._lcspline[ind].knots  = knots
                
            if dim==1:
                self._lcspline[ind].conf   = f"c{par[-1]}:d{deg}k{knots}"
            else:
                self._lcspline[ind].conf   = f"c{par[0][-1]}:d{deg[0]}K{knots[0]}|c{par[1][-1]}:d{deg[1]}k{knots[1]}"

            if verbose: print(f"{lc} – Adding a degree {deg} spline to fit {par}: knot spacing = {knots} --> [{self._lcspline[ind].conf}]") 
        
        if verbose: _print_output(self,"lc_baseline")


    def add_GP(self ,lc_list=None, par=["col0"], kernel=["mat32"], operation=[""],
                 amplitude=[], lengthscale=[], verbose=True):
        """  
            Define GP parameters for each lc.
            The GP parameters, amplitude in ppm  and lengthscale in unit of the desired column can be defined in following ways:
            * fixed value as float or int, e.g amplitude = 2
            * free parameter with lognormal prior given as tuple of len 2, e.g. amplitude = (2, 1)
            * free parameters with loguniform prior interval and initial value given as tuple of length 3, e.g. amplitude = (1,2,5) with 2 being the initial value.
            
            Here the amplitude corresponds to the standard deviation of the noise process and the lengthscale corresponds to the characteristic timescale of the noise process.
            
            For the celerite sho kernel, the quality factor Q has been fixed to 1/sqrt(2) which is commonly used to model stellar oscillations/granulation noise (eqn 24 celerite paper).
            this lengthscale here is the undamped period of the oscillator.

            For the cosine kernel in George, lengthscale is the period. This kernel should probably always be multiplied by a stationary kernel (e.g. ExpSquaredKernel) to allow quasi-periodic variations.

            Parameters:
            -----------
            lc_list : str, list;
                list of lc files to add GP to. Default is None for no GP. if "all" is given, GP is added to all lc files where gp use has been indicated in ``lc_baseline()``. 
                If "same" is given, a global (same) GP is used for all indicated lc files in ``lc_baseline()``.
            par : str, tuple, list;
                column of the input data to use as the GP independent variable. a list is expected if different columns are to be used for the lc files given in lc_list.
                to use 2 different kernels on a single lc file, give column name for each kernel as a tuple of length 2. 
                e.g. lc_list=["lc1.dat","lc2.dat"], par = [("col0","col0"),"col3"] to use col0 for both kernels of lc1, and col3 for lc2.
            kernel : str, tuple, list;
                kernel to use for the GP. Must be one of ["mat32","mat52","exp","expsq","cos"] if George package is selected  and one of ["real","mat32","sho"] if using Celerite package
                A list is expected if different kernels are to be used for the lc files given in lc_list.
                to use 2 different kernels on a single lc file, give kernel name for each kernel as a tuple of length 2.
                e.g. lc_list=["lc1.dat","lc2.dat"], kernel = [("mat32","expsq"),"exp"] to use mat32 and expsq for lc1, and exp for lc2.
            operation : str, tuple, list;
                operation to combine 2 kernels. Must be one of ["+","*"]. Default is "" for no combination.
            amplitude : float, tuple, list;
                amplitude of the GP kernel. Must be list containing int/float or tuple of length 2 or 3
            lengthscale : float, tuple, list;
                lengthscale of the GP kernel. Must be list containing int/float or tuple of length 2 or 3
            verbose : bool;
                print output. Default is True.        
        """
        # supported 2-hyperparameter kernels
        george_allowed   = dict(kernels = ["mat32","mat52","exp","expsq","cos"],columns= ["col0","col3","col4","col5"])
        celerite_allowed = dict(kernels = ["real","mat32","sho"], columns=["col0"])

        self._GP_dict  = {}
        self._sameLCgp  = SimpleNamespace(flag = False, first_index =None)

        if lc_list is None:
            if self._nphot>0:
                if len(self._gp_lcs())>0: print(f"\nWarning: GP was expected for the following lcs {self._gp_lcs()} \nMoving on ...")
                if verbose:_print_output(self,"gp")
            return
        elif isinstance(lc_list, str): 
            if lc_list == "same":
                self._sameLCgp.flag        = True
                self._sameLCgp.first_index = self._names.index(lc_list[0])
            if lc_list in ["all","same"]:
                lc_list = self._gp_lcs()
            else: lc_list=[lc_list]


        for lc in self._gp_lcs(): assert lc in lc_list,f"add_GP(): GP was expected for {lc} but was not given in lc_list."
        for lc in lc_list: 
            assert lc in self._names,f"add_GP(): {lc} not in loaded lc files."
            assert lc in self._gp_lcs(),f"add_GP(): GP was not expected for {lc} but was given in lc_list. Use `._useGPphot` attribute to modify this list with 'y','ce' or 'n' for each loaded lc"
        
        lc_ind = [self._names.index(lc) for lc in lc_list]
        gp_pck = [self._useGPphot[i] for i in lc_ind]   #gp_pck is a list of "y" or "ce" for each lc in lc_list

        DA = locals().copy()
        _  = [DA.pop(item) for item in ["self","verbose","lc"]]

        for p in ["par","kernel","operation","amplitude","lengthscale"]:
            if isinstance(DA[p], (str,int,float,tuple)): DA[p] = [DA[p]]
            if isinstance(DA[p], list): 
                if self._sameLCgp.flag: 
                    assert len(DA[p])==1, f"add_GP(): {p} must be a list of length {len(lc_list)} or length 1 (if same is to be used for all LCs)."
                DA[p] = DA[p]*len(lc_list)

            assert len(DA[p])==len(lc_list), f"add_GP(): {p} must be a list of length {len(lc_list)} or length 1 (if same is to be used for all LCs)."
            
        for p in ["par","kernel","operation","amplitude","lengthscale"]:
            #check if inputs for p are valid
            for i,list_item in enumerate(DA[p]):
                if p=="par":
                    if isinstance(list_item, str): 
                        if gp_pck[i]=="y":  assert list_item in george_allowed["columns"],  f'add_GP(): inputs of {p} must be in {george_allowed["columns"]}   but {list_item} given.'
                        if gp_pck[i]=="ce": assert list_item in celerite_allowed["columns"],f'add_GP(): inputs of {p} must be in {celerite_allowed["columns"]} but {list_item} given.'
                        DA["operation"][i] = ""
                    elif isinstance(list_item, tuple): 
                        assert len(list_item)==2,f'add_GP(): max of 2 gp kernels can be combined, but {list_item} given in {p}.'
                        assert DA["operation"][i] in ["+","*"],f'add_GP(): operation must be one of ["+","*"] to combine 2 kernels but {DA["operation"][i]} given.'
                        for tup_item in list_item: 
                            if gp_pck[i]=="y":  assert tup_item in george_allowed["columns"],  f'add_GP(): {p} must be in {george_allowed["columns"]}   but {tup_item} given.'
                            if gp_pck[i]=="ce": assert tup_item in celerite_allowed["columns"],f'add_GP(): {p} must be in {celerite_allowed["columns"]} but {tup_item} given.'
                        # assert that a tuple of length 2 is also given for kernels, amplitude and lengthscale.
                        for chk_p in ["kernel","amplitude","lengthscale"]:
                            assert isinstance(DA[chk_p][i], tuple) and len(DA[chk_p][i])==2,f'add_GP(): expected tuple of len 2 for {chk_p} element {i} but {DA[chk_p][i]} given.'
                            
                    else: _raise(TypeError, f"add_GP(): elements of {p} must be a tuple of length 2 or str but {list_item} given.")
                
                if p=="kernel":
                    if isinstance(list_item, str): 
                        if gp_pck[i]=="y":  assert list_item in george_allowed["kernels"],  f'add_GP(): {p} must be one of {george_allowed["kernels"]}   but {list_item} given.'
                        if gp_pck[i]=="ce": assert list_item in celerite_allowed["kernels"],f'add_GP(): {p} must be one of {celerite_allowed["kernels"]} but {list_item} given.'
                    elif isinstance(list_item, tuple):
                        for tup_item in list_item: 
                            if gp_pck[i]=="y":  assert tup_item in george_allowed["kernels"],  f'add_GP(): {p} must be one of {george_allowed["kernels"]}   but {tup_item} given.'
                            if gp_pck[i]=="ce": assert tup_item in celerite_allowed["kernels"],f'add_GP(): {p} must be one of {celerite_allowed["kernels"]} but {tup_item} given.'
                    else: _raise(TypeError, f"add_GP(): elements of {p} must be a tuple of length 2 or str but {list_item} given.")

                if p=="operation":
                    assert list_item in ["+","*",""],f'add_GP(): {p} must be one of ["+","*",""] but {list_item} given.'

                if p in ["amplitude", "lengthscale"]:
                    if isinstance(list_item, (int,float)): pass
                    elif isinstance(list_item, tuple):
                        if isinstance(DA["par"][i],tuple):
                            for tup in list_item:
                                if isinstance(tup, (int,float)): pass
                                elif isinstance(tup, tuple): 
                                    assert len(tup) in [2,3],f'add_GP(): {p} must be a float/int or tuple of length 2/3 but {tup} given.'
                                    if len(tup)==3: assert tup[0]<tup[1]<tup[2],f'add_GP(): uniform prior for {p} must follow (min, start, max) but {tup} given.'
                                else: _raise(TypeError, f"add_GP(): elements of {p} must be a tuple of length 23 or float/int but {tup} given.")
                        else:
                            assert len(list_item) in [2,3],f'add_GP(): {p} must be a float/int or tuple of length 2/3 but {tup} given.'
                            if len(list_item)==3: assert list_item[0]<list_item[1]<list_item[2],f'add_GP(): uniform prior for {p} must follow (min, start, max) but {list_item} given.'
                    else: _raise(TypeError, f"add_GP(): elements of {p} must be a tuple of length 2/3 or float/int but {list_item} given.")


        #setup parameter objects
        for i,lc in enumerate(lc_list):
            self._GP_dict[lc] = {}
            ngp = 2 if isinstance(DA["kernel"][i],tuple) else 1
            self._GP_dict[lc]["ngp"] = ngp
            self._GP_dict[lc]["op"]  = DA["operation"][i]

            for p in ["amplitude", "lengthscale"]:
                for j in range(ngp):
                    if ngp==1: 
                        v = DA[p][i]
                        this_kern, this_par = DA["kernel"][i], DA["par"][i]
                    else:
                        v = DA[p][i][j]
                        this_kern, this_par = DA["kernel"][i][j], DA["par"][i][j]

                    if isinstance(v, (int,float)):
                        self._GP_dict[lc][p+str(j)]     = _param_obj(to_fit="n", start_value=v,step_size=0,
                                                                        prior="n", prior_mean=v, prior_width_lo=0,
                                                                        prior_width_hi=0, bounds_lo=0.01, bounds_hi=0,
                                                                        user_data = [this_kern, this_par])
                    elif isinstance(v, tuple):
                        if len(v)==2:
                            steps = 0 if (self._sameLCgp.flag and i!=0) else 0.1*v[1]   #if sameRVgp is set, only first pars will jump and be used for all rvs
                            self._GP_dict[lc][p+str(j)] = _param_obj(to_fit="y", start_value=v[0],step_size=steps,prior="p", 
                                                                        prior_mean=v[0], prior_width_lo=v[1], prior_width_hi=v[1], 
                                                                        bounds_lo=v[0]-10*v[1], bounds_hi=v[0]+10*v[1],
                                                                        user_data=[this_kern, this_par])
                        elif len(v)==3:
                            steps = 0 if (self._sameLCgp.flag and i!=0) else min(0.001,0.001*np.ptp(v))
                            self._GP_dict[lc][p+str(j)] = _param_obj(to_fit="y", start_value=v[1],step_size=steps,
                                                                        prior="n", prior_mean=v[1], prior_width_lo=0,
                                                                        prior_width_hi=0, bounds_lo=v[0] if v[0]>0 else 0.007, bounds_hi=v[2],
                                                                        user_data=[this_kern, this_par])
                    else: _raise(TypeError, f"add_GP(): elements of {p} must be a tuple of length 2/3 or float/int but {v} given.")

        if verbose: _print_output(self,"gp")
    
    
    def planet_parameters(self, RpRs=0., Impact_para=0, rho_star=0, T_0=0, Period=0, 
                            Eccentricity=0, omega=90, K=0, verbose=True):
        """
            Define parameters an priors of model parameters.
            By default, the parameters are fixed to the given values. To fit a parameter use the `to_fit` method to change it from 'n' to 'y'.
            The parameters can be defined in following ways:
            
            * fixed value as float or int, e.g Period = 3.4
            * free parameter with gaussian prior given as tuple of len 2, e.g. T_0 = (5678, 0.1)
            * free parameters with uniform prior interval and initial value given as tuple of length 3, e.g. RpRs = (0,0.1,0.2) with 0.1 being the initial value.

            Parameters:
            -----------
            RpRs : float, tuple;
                Ratio of planet to stellar radius. Default is 0.

            Impact_para : float, tuple;
                Impact parameter of the transit. Default is 0.

            rho_star : float, tuple;
                density of the star in g/cm^3. Default is 0.

            T_0 : float, tuple;
                Mid-transit time in days. Default is 0.

            Period : float, tuple;
                Orbital period of the planet in days. Default is 0.

            Eccentricity : float, tuple;
                Eccentricity of the orbit. Default is 0.

            omega : float, tuple;
                Argument of periastron om degrees. Default is 90.

            K : float, tuple;
                Radial velocity semi-amplitude in same unit as the data. Default is 0.

            verbose : bool;
                print output. Default is True.
        """
        
        DA = locals().copy()         #dict of arguments (DA)
        _ = DA.pop("self")                            #remove self from dictionary
        _ = DA.pop("verbose")
        #sort to specific order
        key_order = ["RpRs","Impact_para","rho_star", "T_0", "Period", "Eccentricity","omega", "K"]
        DA = {key:DA[key] for key in key_order if key in DA} 
            
        self._TR_RV_parnames  = [nm for nm in DA.keys()] 
        # self._npars = 8
        self._config_par = {}

        for par in DA.keys():
            if isinstance(DA[par], (float,int,tuple)): DA[par] = [DA[par]]*self._nplanet
            if isinstance(DA[par], list): assert len(DA[par])==self._nplanet, f"planet_parameters: {par} must be a list of length {self._nplanet} or float/int/tuple."

        for n in range(self._nplanet):    #n is planet number
            self._config_par[f"pl{n+1}"] = {}

            for par in DA.keys():
                if par in ["RpRs", "Eccentricity"]: lo_lim,up_lim = 0,1
                elif par == "rho_star":    lo_lim,up_lim = 0,8
                elif par == "Impact_para": lo_lim,up_lim = 0,2
                elif par == "omega":       lo_lim,up_lim = 0,360

                #fitting parameter
                if isinstance(DA[par][n], tuple):
                    #gaussian       
                    if len(DA[par][n]) == 2:
                        if par in ["T_0","rho_star","Period"]: 
                            lo_lim = DA[par][n][0]-20*DA[par][n][1] if par=="T_0" else max(0,DA[par][n][0]-20*DA[par][n][1])    #lowlim is mean-20*sigma
                            up_lim = DA[par][n][0]+20*DA[par][n][1]    #uplim is mean+20*sigma   
                        DA[par][n] = _param_obj(to_fit="y", start_value=DA[par][n][0], step_size=0.1*DA[par][n][1],
                                                prior="p", prior_mean=DA[par][n][0],  
                                                prior_width_lo=DA[par][n][1], prior_width_hi=DA[par][n][1], 
                                                bounds_lo=lo_lim, bounds_hi=up_lim)
                    #uniform
                    elif len(DA[par][n]) == 3: 
                        DA[par][n] = _param_obj(*["y", DA[par][n][1], min(0.001,0.001*np.ptp(DA[par][n])), "n", DA[par][n][1],
                                                        0, 0, DA[par][n][0], DA[par][n][2]])
                    
                    else: _raise(ValueError, f"planet_parameters: length of tuple {par} is {len(DA[par][n])} but it must be 2 for gaussian or 3 for uniform priors")
                #fixing parameter
                elif isinstance(DA[par][n], (int, float)):
                    DA[par][n] = _param_obj(*["n", DA[par][n], 0.00, "n", DA[par][n], 0, 0, 0, 0])

                else: _raise(TypeError, f"planet_parameters(): {par} for planet{n} must be one of [tuple(of len 2 or 3), int, float] but is {type(DA[par][n])}")

                self._config_par[f"pl{n+1}"][par] = DA[par][n]      #add to object
        
        if verbose: _print_output(self,"planet_parameters")

        if self._show_guide: print("\nNext: use method transit_depth_variation` to include variation of RpRs for the different filters or \n`setup_phasecurve` to fit the occultation depth or \n`limb_darkening` for fit or fix LDCs or `contamination_factors` to add contamination.")


    def update_planet_parameters(self, RpRs=0., Impact_para=0, rho_star=0, T_0=0, Period=0, 
                 Eccentricity=0, omega=90, K=0, verbose=True):
        """
            update parameters and priors of model parameters.
            By default, the parameters are fixed to the given values. To fit a parameter use the `to_fit` method to change it from 'n' to 'y'.
            The parameters can be defined in following ways:
            
            * fixed value as float or int, e.g Period = 3.4
            * free parameter with gaussian prior given as tuple of len 2, e.g. T_0 = (5678, 0.1)
            * free parameters with uniform prior interval and initial value given as tuple of length 3, e.g. RpRs = (0,0.1,0.2) with 0.1 being the initial value.

            Parameters:
            -----------
            RpRs : float, tuple;
                Ratio of planet to stellar radius. Default is 0.

            Impact_para : float, tuple;
                Impact parameter of the transit. Default is 0.

            rho_star : float, tuple;
                density of the star in g/cm^3. Default is 0.

            T_0 : float, tuple;
                Mid-transit time in days. Default is 0.

            Period : float, tuple;
                Orbital period of the planet in days. Default is 0.

            Eccentricity : float, tuple;
                Eccentricity of the orbit. Default is 0.

            omega : float, tuple;
                Argument of periastron. Default is 90.

            K : float, tuple;
                Radial velocity semi-amplitude in m/s. Default is 0.

            verbose : bool;
                print output. Default is True.
        """
        
        DA = locals().copy()         #dict of arguments (DA)
        _ = DA.pop("self")                            #remove self from dictionary
        _ = DA.pop("verbose")

        rm_par= []
        for par in DA.keys():
            if DA[par] == 0: rm_par.append(par)
        _ = [DA.pop(p) for p in rm_par]
        

        for par in DA.keys():
            if isinstance(DA[par], (float,int,tuple)): DA[par] = [DA[par]]*self._nplanet
            if isinstance(DA[par], list): assert len(DA[par])==self._nplanet, f"planet_parameters: {par} must be a list of length {self._nplanet} or float/int/tuple."

        for n in range(self._nplanet):    #n is planet number

            for par in DA.keys():
                if par in ["RpRs", "Eccentricity"]: lo_lim,up_lim = 0,1
                elif par == "rho_star":    lo_lim,up_lim = 0,8
                elif par == "Impact_para": lo_lim,up_lim = 0,2
                elif par == "omega":       lo_lim,up_lim = 0,360

                #fitting parameter
                if isinstance(DA[par][n], tuple):
                    #gaussian       
                    if len(DA[par][n]) == 2:
                        if par in ["T_0","rho_star","Period"]: 
                            lo_lim = DA[par][n][0]-20*DA[par][n][1] if par=="T_0" else max(0,DA[par][n][0]-20*DA[par][n][1])    #lowlim is mean-20*sigma
                            up_lim = DA[par][n][0]+20*DA[par][n][1]    #uplim is mean+20*sigma   
                        DA[par][n] = _param_obj(to_fit="y", start_value=DA[par][n][0], step_size=0.1*DA[par][n][1],
                                                prior="p", prior_mean=DA[par][n][0],  
                                                prior_width_lo=DA[par][n][1], prior_width_hi=DA[par][n][1], 
                                                bounds_lo=lo_lim, bounds_hi=up_lim)
                    #uniform
                    elif len(DA[par][n]) == 3: 
                        DA[par][n] = _param_obj(*["y", DA[par][n][1], min(0.001,0.001*np.ptp(DA[par][n])), "n", DA[par][n][1],
                                                        0, 0, DA[par][n][0], DA[par][n][2]])
                    
                    else: _raise(ValueError, f"update_planet_parameters(): length of tuple {par} is {len(DA[par][n])} but it must be 2 for gaussian or 3 for uniform priors")
                #fixing parameter
                elif isinstance(DA[par][n], (int, float)):
                    DA[par][n] = _param_obj(*["n", DA[par][n], 0.00, "n", DA[par][n], 0, 0, 0, 0])

                else: _raise(TypeError, f"update_planet_parameters(): {par} for planet{n} must be one of [tuple(of len 2 or 3), int, float] but is {type(DA[par][n])}")

                self._config_par[f"pl{n+1}"][par] = DA[par][n]      #add to object
        
        if verbose: _print_output(self,"planet_parameters")

        if self._show_guide: print("\nNext: use method transit_depth_variation` to include variation of RpRs for the different filters or \n`setup_phasecurve` to fit the occultation depth or \n`limb_darkening` for fit or fix LDCs or `contamination_factors` to add contamination.")


    def transit_depth_variation(self, ddFs="n", dRpRs=(-0.5,0,0.5), divwhite="n",  verbose=True):
        """
            Include transit depth variation between the different lcs or lc groups. Note: "RpRs" must be fixed to a reference value  in `.planet_parameters()` and not a jump parameter .
            transit depth variation is calculated as the deviation of each group's transit depth from the fixed RpRs
            
            Parameters:
            -----------

            ddFs : str ("y" or "n");
                specify if to fit depth variation or not. default is "n"

            dRpRs : tuple of len 2 or 3;
                deviation of depth in each group from the reference values. Must be tuple of len 2/3 specifying (mu,std)/(min,start,max) 

            divwhite : str ("y" or "n");
                flag to divide each light-curve by the white lightcurve. Default is "n"

            verbose: bool;
                print output
                  
        """
        assert hasattr(self, "_config_par"), "transit_depth_variation(): planet_parameters() must be called before transit_depth_variation()."
        assert isinstance(dRpRs, tuple),f"transit_depth_variation(): dRpRs must be tuple of len 2/3 specifying (mu,std)/(min,start,max)."
        if ddFs == "y": assert self._config_par["pl1"]["RpRs"].to_fit == "n",'Fix `RpRs` in `planet_parameters` to a reference value in order to setup depth variation.'
        
            
        grnames    = np.array(list(sorted(set(self._groups))))
        ngroup     = len(grnames)
        transit_depth_per_group = [(self._config_par["pl1"]["RpRs"].start_value,0)]
        depth_per_group     = [d[0] for d in transit_depth_per_group] * ngroup  # depth for each group
        depth_err_per_group = [d[1] for d in transit_depth_per_group] * ngroup 
        step = 0.001

        if len(dRpRs)==3: 
            start_val = dRpRs[1]
            bounds_lo,bounds_hi = dRpRs[0],dRpRs[2]
            prior_width_lo = prior_width_hi = 0
        else: 
            start_val = dRpRs[0]
            bounds_lo, bounds_hi = -0.5, 0.5
            prior_width_lo = prior_width_hi = dRpRs[1]

        self._ddfs= SimpleNamespace()
        self._ddfs.drprs_op=[start_val, step, bounds_lo, bounds_hi, start_val, prior_width_lo, prior_width_hi]  # the dRpRs options


        self._ddfs.depth_per_group     = depth_per_group
        self._ddfs.depth_err_per_group = depth_err_per_group
        self._ddfs.divwhite            = divwhite
        # self._ddfs.prior               = prior
        self._ddfs.ddfYN               = ddFs
        self._ddfs.prior_width_lo      = prior_width_lo
        self._ddfs.prior_width_hi      = prior_width_hi
        if divwhite=="y":
            assert ddFs=='n', 'transit_depth_variation(): you can not do divide-white and not fit ddfs!'
            
            for i in range(self._nphot):
                if (self._bases[i][6]>0):
                    _raise(ValueError, 'transit_depth_variation(): you can not have CNMs active and do divide-white')
        
        if self._nphot>0: 
            if (ddFs=='n' and np.max(self._grbases)>0): _raise(ValueError,'no ddFs but groups? Not a good idea!')
            
        if verbose: _print_output(self,"depth_variation")
                
    
    def setup_phasecurve(self, D_occ=0, A_pc=0, ph_off=0, verbose=True ):
        """
            Setup phase curve parameters for each unique filter in loaded lightcurve. use `._fil_names` attribute to see the unique filter order.
            
            Parameters:
            -----------
            D_occ : float, tuple, list;
                Occultation depth. Default is 0.

            A_pc : float, tuple, list;
                Amplitude of the phase curve. Default is 0.

            ph_off : float, tuple,list;
                Offset of the hotspot in degrees. Default is 0.

            verbose : bool;
                print output. Default is True.
        """
        DA = locals().copy()
        _  = [DA.pop(item) for item in ["self","verbose"]]

        nfilt  = len(self._filnames)    #length of unique filters

        for par in DA.keys():
            if isinstance(DA[par], (int,float,tuple)): DA[par] = [DA[par]]*nfilt
            if isinstance(DA[par], list):
                if len(DA[par])==1: DA[par] = DA[par]*nfilt
            assert len(DA[par])==nfilt, \
                        f"setup_phasecurve(): {par} must be a list of length {nfilt} (for filters {list(self._filnames)}) or float/int/tuple."
        
        #occ_depth
        self._PC_dict = dict(D_occ = {}, A_pc = {}, ph_off = {})     #dictionary to store phase curve parameters
        for par in DA.keys():      #D_occ, A_pc, ph_off
            for i,f in enumerate(self._filnames):    
                v = DA[par][i]
                if isinstance(v, tuple):   
                    #recall: _param_obj([to_fit, start_value, step_size,prior, prior_mean,pr_width_lo,prior_width_hi, bounds_lo, bounds_hi])
                    step = 1 if par=="ph_off" else 1e-6
                    if len(v) == 2:                 #gaussian  prior
                        self._PC_dict[par][f] = _param_obj(*["y", v[0], step, "p", v[0], v[1], v[1], 0, 1])
                    elif len(v) == 3:               #uniform prior
                        self._PC_dict[par][f] = _param_obj(*["y", v[1], step, "n", v[1], 0, 0, v[0], v[2]])
                    else: _raise(ValueError, f"setup_phasecurve(): length of tuple {par} is {len(v)} but it must be 2 for gaussian or 3 for uniform priors")
                
                elif isinstance(v, (int, float)):   #fixed value
                    self._PC_dict[par][f] = _param_obj(*["n", v, 0.00, "n", v, 0, 0, 0, 0])
                
                else: _raise(TypeError, f"setup_phasecurve(): {par} must be one of [tuple(of len 2 or 3), float] but {v} is given for filter {f}.")

        if verbose: _print_output(self,"phasecurve")

    def get_LDs(self,Teff,logg,Z, filter_names, unc_mult=10, use_result=False, verbose=True):
        """
        get Kipping quadratic limb darkening parameters (q1,q2) using ldtk (requires internet connection).

        Parameters
        ----------
        Teff : tuple
            (value, std) of stellar effective temperature

        logg : tuple
            (value, std) of stellar logg

        Z : tuple
            (value, std) of stellar metallicity

        filter_names : list of str
            SVO filter name such as 'Spitzer/IRAC.I1' or a name shortcut such as "TESS", "CHEOPS","kepler". 
            use `lc_obj._filter_shortcuts` to get list of filter shortcut names. Filter names can be obtained from http://svo2.cab.inta-csic.es/theory/fps/

        unc_mult : int/float, optional
            value by which to multiply ldtk uncertainties which are usually underestimated, by default 10

        use_result : bool, optional
            whether to use the result to setup limb darkening priors, by default True

        Returns
        -------
        q1, q2 : arrays
            each coefficient is an array of only values (no uncertainity) for each filter. 
            These can be fed to the `limb_darkening()` function to fix the coefficients
        """

        from ldtk import LDPSetCreator, BoxcarFilter
        q1, q2 = [], []
        
        if isinstance(filter_names,list): 
            assert len(filter_names)==len(self._filnames),\
                f"get_LDs: number of unique filters in input lc_list = {len(self._filnames)} but trying to obtain LDs for {len(filter_names)} filters."
        elif isinstance(filter_names, str): filter_names = [filter_names]
        else: raise TypeError(f"get_LDs: filter_names must be str for a single filter or list of str but {type(filter_names)} given.")

        for i,f in enumerate(filter_names):
            if f.lower() in self._filter_shortcuts.keys(): ft = self._filter_shortcuts[f.lower()]
            else: ft=f
            flt = SVOFilter(ft)
            ds  = 'visir-lowres' if np.any(flt.wavelength > 1000) else 'vis-lowres'

            sc  = LDPSetCreator(teff=Teff, logg=logg, z=Z,    # spectra from the Husser et al.
                                filters=[flt], dataset=ds)      # FTP server automatically.

            ps = sc.create_profiles(100)                      # Create the limb darkening profiles\
            ps.set_uncertainty_multiplier(unc_mult)
            ps.resample_linear_z(300)

            #calculate ld profiles
            c, e = ps.coeffs_tq(do_mc=True, n_mc_samples=10000,mc_burn=1000) 
            ld1 = (round(c[0][0],4),round(e[0][0],4))
            ld2 = (round(c[0][1],4),round(e[0][1],4))
            q1.append(ld1)
            q2.append(ld2)
            if verbose: print(f"{f:10s}({self._filters[i]}): q1={ld1}, q2={ld2}")

        if use_result: 
            q_1 = deepcopy(q1)
            q_2 = deepcopy(q2)
            if verbose: print(_text_format.BOLD + "\nSetting-up limb-darkening priors from LDTk result" +_text_format.END)
            self.limb_darkening(q_1,q_2)
        return q1,q2



    def limb_darkening(self, q1=0, q2 = 0,verbose=True):
        """
            Setup Kipping quadratic limb darkening LD coefficient (q1, q2) for transit light curves. 
            Different LD coefficients are required if observations of different filters are used.

            Parameters:
            -----------
            q1,q2 : float/tuple or list of float/tuple for each filter;
                Stellar quadratic limb darkening coefficients.
                if tuple, must be of - length 2 for normal prior (mean,std) or length 3 for uniform prior defined as (lo_lim, val, uplim).
                The values must obey: (0<q1<1) and (0<=q2<1)

        """
        #defaults
        bound_lo1 = bound_lo2 = 0
        bound_hi1 = bound_hi2 = 0
        sig_lo1 = sig_lo2 = 0
        sig_hi1 = sig_hi2 = 0
        step1 = step2 = 0 
        # prior_type1 = prior_type2 = "F"    

        DA = deepcopy(locals())
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("verbose")

        nfilt = len(self._filnames)

        for par in DA.keys():
            if isinstance(DA[par], (int,float,tuple,str)): DA[par] = [DA[par]]*nfilt
            elif isinstance(DA[par], list): assert len(DA[par]) == nfilt,f"limb_darkening(): length of list {par} must be equal to number of unique filters (={nfilt})."
            else: _raise(TypeError, f"limb_darkening(): {par} must be int/float, or tuple of len 2 (for gaussian prior) or 3 (for uniform prior) but {DA[par]} is given.")
        
        for par in ["q1","q2"]:
            for i,d in enumerate(DA[par]):
                if isinstance(d, (int,float)):  #fixed
                    DA[par][i] = d
                    DA[f"step{par[-1]}"][i] = DA[f"bound_lo{par[-1]}"][i] = DA[f"bound_hi{par[-1]}"][i] = 0
                    # DA[f"prior_type{par[-1]}"][i] = "F"
                elif isinstance(d, tuple):
                    if len(d) == 2:  #normal prior
                        DA[par][i] = d[0]
                        DA[f"sig_lo{par[-1]}"][i] = DA[f"sig_hi{par[-1]}"][i] = d[1]
                        DA[f"bound_lo{par[-1]}"][i] = 0
                        DA[f"bound_hi{par[-1]}"][i] = 1
                        DA[f"step{par[-1]}"][i] = 0.1*DA[f"sig_lo{par[-1]}"][i]
                        # DA[f"prior_type{par[-1]}"][i] = "N"

                    if len(d) == 3:  #uniform prior
                        assert d[0]<=d[1]<=d[2],f'limb_darkening(): uniform prior be (lo_lim, start_val, uplim) where lo_lim <= start_val <= uplim but {d} given.'
                        assert (d[0]>=0  and d[2]<=1),f'limb_darkening(): uniform prior must be (lo_lim, val, uplim) where lo_lim>=0 and uplim<=1 but {d} given.'
                        DA[par][i] = d[1]
                        DA[f"bound_lo{par[-1]}"][i] = d[0]
                        DA[f"bound_hi{par[-1]}"][i] = d[2]
                        DA[f"sig_lo{par[-1]}"][i] = DA[f"sig_hi{par[-1]}"][i] = 0
                        DA[f"step{par[-1]}"][i] = min(0.001, np.ptp([d[0],d[2]]))
                        # DA[f"prior_type{par[-1]}"][i] = "U"

        DA["priors"] = [0]*nfilt
        for i in range(nfilt):
            DA["priors"][i] = "y" if np.any( [DA["sig_lo1"][i], DA["sig_lo2"][i] ]) else "n"

        self._ld_dict = DA
        if verbose: _print_output(self,"limb_darkening")

    def contamination_factors(self, cont_ratio=0, verbose=True):
        """
            add contamination factor for each unique filter defined from load_lightcurves().

            Paramters:
            ----------
            cont_ratio: list, float;
                ratio of contamination flux to target flux in aperture for each filter. The order of list follows lc_obj._filnames.
                Very unlikely but if a single float/tuple is given for several filters, same cont_ratio is used for all.
        """

        DA = locals().copy()
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("verbose")

        nfilt = len(self._filnames)


        for par in DA.keys():
            if isinstance(DA[par], (int,float)): DA[par] = [(DA[par],0)]*nfilt
            elif isinstance(DA[par], list):
                assert len(DA[par]) == nfilt, f"contamination_factors(): length of input {par} must be equal to the length of unique filters (={nfilt}) or float."
                for i in range(nfilt):
                    if isinstance(DA[par][i], (int,float)): DA[par][i] = (DA[par][i],0)
            else: _raise(TypeError, f"contamination_factors(): {par} must be a float but {DA[par]} given.")
            
        self._contfact_dict = DA
        if verbose: _print_output(self,"contamination")

    def __repr__(self):
        data_type = str(self.__class__).split("load_")[1].split("'>")[0]
        self.print("lc_baseline")
        if self._nphot>0:
            return f'{data_type} from filepath: {self._fpath}\n{self._nplanet} transiting planet(s)\nOrder of unique filters: {list(self._filnames)}'
        else:
            return ""
    def print(self, section="all"):
        """
            Print out all input configuration (or particular section) for the light curve object. 
            It is printed out in the format of the legacy CONAN config file.
            Parameters:
            ------------
            section : str (optional) ;
                section of configuration to print.Must be one of ["lc_baseline", "gp", "planet_parameters", "depth_variation", "occultations", "limb_darkening", "contamination", "stellar_pars"].
                Default is 'all' to print all sections.
        """
        if section=="all":
            _print_output(self,"lc_baseline")
            _print_output(self,"gp")
            _print_output(self,"planet_parameters")
            _print_output(self,"depth_variation")
            _print_output(self,"phasecurve")
            _print_output(self,"limb_darkening")
            _print_output(self,"contamination")
        else:
            possible_sections= ["lc_baseline", "gp", "planet_parameters", "depth_variation",
                                 "phasecurve", "limb_darkening", "contamination", "stellar_pars"]
            assert section in possible_sections, f"print: {section} not a valid section of `lc_obj`. \
                section must be one of {possible_sections}."
            _print_output(self, section)

    def plot(self, plot_cols=(0,1,2), col_labels=None, nrow_ncols=None, figsize=None, fit_order=0, show_decorr_model=False, return_fig=False):
        """
            visualize data

            Parameters:
            -----------
            plot_cols : tuple of length 2 or 3;
                Tuple specifying which columns in input file to plot. 
                Default is (0,1,2) to plot column 0 against 1, and 2 as errorbar (i.e. time against flux with fluxerr). 
                Use (3,1,2) to show the correlation between column 3 and the flux. 
                Using tuple of length 2 does not plot errorbars. e.g (3,1).

            col_labels : tuple of length 2;
                label of the given columns in plot_cols. Default is ("time", "flux").
            
            nrow_ncols : tuple of length 2;
                Number of rows and columns to plot the input files. 
                Default is None to find the best layout.

            fit_order : int;
                order of polynomial to fit to the plotted data columns to visualize correlation.

            show_decorr_model : bool;
                show decorrelation model if decorrelation has been done.
            
            figsize: tuple of length 2;
                Figure size. If None, (8,5) is used for a single input file and optimally determined for more inputs.

            return_fig  : bool;
                return figure object for saving to file.
        """
        if not (isinstance(plot_cols, tuple) and len(plot_cols) in [2,3]): 
            raise TypeError(f"plot: plot_cols must be tuple of length 2 or 3, but is {type(plot_cols)} and length of {len(plot_cols)}.")
        
        assert col_labels is None or ((isinstance(col_labels, tuple) and len(col_labels)==2)), \
            f"plot: col_labels must be tuple of length 2, but is {type(col_labels)} and length of {len(col_labels)}."
        
        assert isinstance(fit_order,int),f'fit_order must be an integer'

        if show_decorr_model:
            if not hasattr(self,"_tmodel"): 
                print("cannot show decorr model since decorrelation has not been done. First, use `lc_obj.get_decorr()` to launch decorrelation.")
                show_decorr_model = False
        
        if col_labels is None:
            col_labels = ("time", "flux") if plot_cols[:2] == (0,1) else (f"column[{plot_cols[0]}]",f"column[{plot_cols[1]}]")
        
        if self._names != []:
            fig = _plot_data(self, plot_cols=plot_cols, col_labels = col_labels, nrow_ncols=nrow_ncols, figsize=figsize, fit_order=fit_order,
                            model_overplot=self._tmodel if show_decorr_model else None)
            if return_fig: return fig
        else: print("No data to plot")
    
        
    
        
#rv data
class load_rvs:
    """
        rv object to hold lightcurves for analysis
        
        Parameters:
        -----------
        data_filepath : str;
            filepath where rvs files are located
            
        file_list : list;
            list of filenames for the rvs

        nplanet : int;
            number of planets in the system. Default is 1.

        rv_unit : str;
            unit of the rv data. Must be one of ["m/s","km/s"]. Default is "km/s".

        lc_obj : object;
            lightcurve object to modify rv parameters

        show_guide : bool;
            print output to guide the user. Default is False.

        Returns:
        --------
        rv_obj : rv object

        Examples:
        ---------
        >>> rv_obj = load_rvs(file_list=["rv1.dat","rv2.dat"], data_filepath="/path/to/data/", rv_unit="km_s")
    """
    def __init__(self, file_list=None, data_filepath=None, nplanet=1, rv_unit="km/s",lc_obj=None,show_guide =False):
        self._obj_type = "rv_obj"
        self._nplanet  = nplanet
        self._fpath    = os.getcwd()+"/" if data_filepath is None else data_filepath
        self._names    = [] if file_list is None else file_list 
        self._input_rv = {}
        self._RVunit  = rv_unit
        self._nRV      = len(self._names)
        self._lcobj    = lc_obj
        
        assert rv_unit in ["m/s","km/s"], f"load_rvs(): rv_unit must be one of ['m/s','km/s'] but {rv_unit} given." 
        if self._names == []:
            self.rv_baseline(verbose=False)
        else: 
            for rv in self._names: assert os.path.exists(self._fpath+rv), f"file {rv} does not exist in the path {self._fpath}."
            if show_guide: print("Next: use method `rv_baseline` to define baseline model for for the each rv")
            
            #modify input files to have 6 columns as CONAN expects
            for f in self._names:
                fdata = np.loadtxt(self._fpath+f)
                nrow,ncol = fdata.shape
                if ncol < 6:
                    print(f"Expected at least 6 columns for RV file: writing ones to the missing columns of file: {f}")
                    new_cols = np.ones((nrow,6-ncol))
                    fdata = np.hstack((fdata,new_cols))
                    np.savetxt(self._fpath+f,fdata,fmt='%.8f')
                #store input files in rv object
                self._input_rv[f] = {}
                for i in range(6): self._input_rv[f][f"col{i}"] = fdata[:,i]

            #list to hold initial baseline model coefficients for each rv
            self._RVbases_init = [dict( A0=0, B0=0, A3=0, B3=0, A4=0, B4=0, A5=0, B5=0, 
                                        amp=0,freq=0,phi=0,phi2=0)
                                    for _ in range(self._nRV)]
            
        self._rescaled_data = SimpleNamespace(flag=False, config="None")
        self.rv_baseline(verbose=False)


    def update_planet_parameters(self, T_0=0, Period=0, Eccentricity=0, omega=90, K=0, verbose=True):
        """
            Update the rv planet parameters defined in the lightcurve object. 

            Parameters:
            -----------
            T_0 : float, tuple;
                Mid-transit time in days. Default is 0.

            Period : float, tuple;
                Orbital period of the planet in days. Default is 0.

            Eccentricity : float, tuple;
                Eccentricity of the orbit. Default is 0.

            omega : float, tuple;
                Argument of periastron. Default is 90.

            K : float, tuple;
                Radial velocity semi-amplitude in same unit as the data. Default is 0.

            verbose : bool;
                print output. Default is True.
        """
        assert self._lcobj is not None, "update_planet_parameters(): lightcurve object not defined. Use `lc_obj` argument in `load_rvs()` to define lightcurve object."
        self._lcobj.update_planet_parameters(T_0=T_0, Period=Period, Eccentricity=Eccentricity, omega=omega, K=K, verbose=verbose)

    def rescale_data_columns(self,method="med_sub", verbose=True):

        """
            Function to rescale the data columns of the RVs. This can be important when decorrelating the data with polynomials.
            The operation is not performed on columns 0,1,2. It is only performed on columns whose values do not span zero.
            Function can only be run once on the loaded datasets but can be reset by running `load_rvs()` again. 

            The method can be one of ["med_sub", "rs0to1", "rs-1to1"] which subtracts the median, rescales to [0,1] or [-1,1] respectively.
        """
        assert method in ["med_sub", "rs0to1", "rs-1to1"], f"method must be one of 'med_sub', 'rs0to1', 'rs-1to1' not {method}"
        
        if self._rescaled_data.flag:
            print("Data columns have already been rescaled. run `load_rvs()` again to reset.")
            return None
        
        for rv in self._names:
            if verbose: print(f"Rescaling data columns of {rv}...")
            for i in range(6):
                if i not in [0,1,2]:
                    if not (min(self._input_rv[rv][f"col{i}"]) <= 0 <=  max(self._input_rv[rv][f"col{i}"])):     #if zero not in array
                        if method == "med_sub":
                            self._input_rv[rv][f"col{i}"] -= np.median(self._input_rv[rv][f"col{i}"])
                        elif method == "rs0to1":
                            self._input_rv[rv][f"col{i}"] = rescale0_1(self._input_rv[rv][f"col{i}"])
                        elif method == "rs-1_1":
                            self._input_rv[rv][f"col{i}"] = rescale_minus1_1(self._input_rv[rv][f"col{i}"])

        self._rescaled_data = SimpleNamespace(flag=True, config=method)

    def get_decorr(self, T_0=None, Period=None, K=None, sesinw=0, secosw=0, gamma=0,
                    delta_BIC=-5, decorr_bound =(-1000,1000), exclude_cols=[],enforce_pars=[],verbose=True, 
                    show_steps=False, plot_model=True, use_result=True):
        """
            Function to obtain best decorrelation parameters for each rv file using the forward selection method.
            It compares a model with only an offset to a polynomial model constructed with the other columns of the data.
            It uses columns 0,3,4,5 to construct the polynomial trend model. The temporary decorr parameters are labelled Ai,Bi for 1st & 2nd order in column i.
            Decorrelation parameters that reduces the BIC by 5(i.e delta_BIC = -5, 12X more probable) are iteratively selected.
            The result can then be used to populate the `rv_baseline()` method, if use_result is set to True.

            Parameters:
            -----------
            T_0, Period, K, Eccentricity, omega : floats, None;
                RV parameters of the planet. T_0 and P must be in same units as the time axis (cols0) in the data file.
                if float/int, the values are held fixed. if tuple/list of len 2 implies [min,max] while len 3 implies [min,start_val,max].

            delta_BIC : float (negative);
                BIC improvement a parameter needs to provide in order to be considered relevant for decorrelation. + \
                    Default is conservative and set to -5 i.e, parameters needs to lower the BIC by 5 to be included as decorrelation parameter.

            decorr_bound: tuple of size 2;
                bounds when fitting decorrelation parameters. Default is (-1000,1000)
                
            exclude_cols : list of int;
                list of column numbers (e.g. [3,4]) to exclude from decorrelation. Default is [].

            enforce_pars : list of int;
                list of decorr params (e.g. ['B3', 'A5']) to enforce in decorrelation. Default is [].

            verbose : Bool, optional;
                Whether to show the table of baseline model obtained. Defaults to True.

            show_steps : Bool, optional;
                Whether to show the steps of the forward selection of decorr parameters. Default is False
            
            plot_model : Bool, optional;
                Whether to overplot suggested trend model on the data. Defaults to True.

            use_result : Bool, optional;
                whether to use result/input to setup the baseline model and transit/eclipse models. Default is True.
        
            Returns
            -------
            decorr_result: list of result object
                list containing result object for each lc.
        """
        assert isinstance(exclude_cols, list), f"get_decorr(): exclude_cols must be a list of column numbers to exclude from decorrelation but {exclude_cols} given."
        for c in exclude_cols: assert isinstance(c, int), f"get_decorr(): column number to exclude from decorrelation must be an integer but {c} given in exclude_cols."
        assert delta_BIC<0,f'get_decorr(): delta_BIC must be negative for parameters to provide improved fit but {delta_BIC} given.'
        if isinstance(gamma, tuple):
            assert len(gamma)==2 or len(gamma)==3,f"get_decorr(): gamma must be float or tuple of length 2/3, but {gamma} given."
        else: assert isinstance(gamma, (int,float)),f"get_decorr(): gamma must be float or tuple of length 2/3, but {gamma} given."

        blpars = {"dcol0":[], "dcol3":[],"dcol4":[], "dcol5":[]}  #inputs to rv_baseline method
        self._rvdecorr_result = []   #list of decorr result for each lc.
        self._rvmodel = []  #list to hold determined trendmodel for each rv
        gamma_init    = []  #list to update gamma prior for each rv based on the lmfit

        self._rv_pars = dict(T_0=T_0, Period=Period, K=K, sesinw=sesinw, secosw=secosw, gamma=gamma) #rv parameters
        for p in self._rv_pars:
            if p != "gamma":
                if isinstance(self._rv_pars[p], (int,float,tuple)): self._rv_pars[p] = [self._rv_pars[p]]*self._nplanet
                if isinstance(self._rv_pars[p], (list)): assert len(self._rv_pars[p]) == self._nplanet, \
                    f"get_decorr(): {p} must be a list of same length as number of planets {self._nplanet} but {len(self._rv_pars[p])} given."


        decorr_cols = [0,3,4,5]
        for c in exclude_cols: assert c in decorr_cols, f"get_decorr(): column number to exclude from decorrelation must be in {decorr_cols} but {c} given in exclude_cols." 
        _ = [decorr_cols.remove(c) for c in exclude_cols]  #remove excluded columns from decorr_cols

        for j,file in enumerate(self._names):
            df = self._input_rv[file]
            if verbose: print(_text_format.BOLD + f"\ngetting decorrelation parameters for rv: {file}" + _text_format.END)
            all_par = [f"{L}{i}" for i in decorr_cols for L in ["A","B"]] 

            out = _decorr_RV(df, **self._rv_pars, decorr_bound=decorr_bound, npl=self._nplanet)    #no trend, only offset
            best_bic = out.bic
            best_pars = {}                      #parameter salways included
            for cp in enforce_pars: best_pars[cp]=0            #add enforced parameters
            _ = [all_par.remove(cp) for cp in enforce_pars if cp in all_par]    #remove enforced parameters from all_par

            if show_steps: print(f"{'Param':7s} : {'BIC':6s} N_pars \n---------------------------")
            del_BIC = -np.inf 
            while del_BIC < delta_BIC:
                if show_steps: print(f"{'Best':7s} : {best_bic:.2f} {len(best_pars.keys())} {list(best_pars.keys())}\n---------------------")
                pars_bic = {}
                for p in all_par:
                    dtmp = best_pars.copy()  #temporary dict to hold parameters to test
                    dtmp[p] = 0
                    out = _decorr_RV(df, **self._rv_pars,**dtmp, decorr_bound=decorr_bound, npl=self._nplanet)
                    if show_steps: print(f"{p:7s} : {out.bic:.2f} {out.nvarys}")
                    pars_bic[p] = out.bic

                par_in = min(pars_bic,key=pars_bic.get)   #parameter that gives lowest BIC
                par_in_bic = pars_bic[par_in]
                del_BIC = par_in_bic - best_bic
                bf = np.exp(-0.5*(del_BIC))
                if show_steps: print(f"+{par_in} -> BF:{bf:.2f}, del_BIC:{del_BIC:.2f}")

                if del_BIC < delta_BIC:# if bf>1:
                    if show_steps: print(f"adding {par_in} lowers BIC to {par_in_bic:.2f}\n" )
                    best_pars[par_in]=0
                    best_bic = par_in_bic
                    all_par.remove(par_in)            

            result = _decorr_RV(df, **self._rv_pars,**best_pars, decorr_bound=decorr_bound, npl=self._nplanet)
            self._rvdecorr_result.append(result)
            print(f"\nBEST BIC:{result.bic:.2f}, pars:{list(best_pars.keys())}")
            
            #calculate determined trend and rv model over all data
            pps = result.params.valuesdict()
            #convert result transit parameters to back to a list
            for p in ["T_0", "Period", "K", "sesinw", "secosw"]:
                if self._nplanet==1:
                    pps[p] = [pps[p]]  
                else:      
                    pps[p] = [pps[p+f"_{n}"] for n in range(1,self._nplanet+1)]
                    _      = [pps.pop(f"{p}_{n}") for n in range(1,self._nplanet+1)]
    
            self._rvmodel.append(_decorr_RV(df,**pps,decorr_bound=decorr_bound, npl=self._nplanet, return_models=True))

            #set-up lc_baseline model from obtained configuration
            blpars["dcol0"].append( 2 if pps["B0"]!=0 else 1 if  pps["A0"]!=0 else 0)
            blpars["dcol3"].append( 2 if pps["B3"]!=0 else 1 if  pps["A3"]!=0 else 0)
            blpars["dcol4"].append( 2 if pps["B4"]!=0 else 1 if  pps["A4"]!=0 else 0)
            blpars["dcol5"].append( 2 if pps["B5"]!=0 else 1 if  pps["A5"]!=0 else 0)
            # store baseline model coefficients for each lc, to used as start values of mcmc
            self._RVbases_init[j] = dict( A0=pps["A0"], B0=pps["B0"],
                                        A3=pps["A3"], B3=pps["B3"], 
                                        A4=pps["A4"], B4=pps["B4"],
                                        A5=pps["A5"], B5=pps["B5"], 
                                        amp=0,freq=0,phi=0,phi2=0)
            
            # adjust gamma prior based on result of the fit to each rv
            if isinstance(gamma, tuple): 
                if len(gamma) ==2: gamma_init.append( (pps["gamma"], gamma[1]))     
                if len(gamma) ==3: gamma_init.append( (gamma[0], pps["gamma"], gamma[2]) )  

        if plot_model:
            _plot_data(self,plot_cols=(0,1,2),col_labels=("time","rv"),model_overplot=self._rvmodel)
        

        #prefill other light curve setup from the results here or inputs given here.
        if use_result:
            if verbose: print(_text_format.BOLD + "Setting-up rv baseline model from result" +_text_format.END)
            self.rv_baseline(dcol0 = blpars["dcol0"], dcol3=blpars["dcol3"], dcol4=blpars["dcol4"],
                                dcol5=blpars["dcol5"], gamma= gamma_init, verbose=verbose)

        return self._rvdecorr_result
    
    def rv_baseline(self, dcol0=None, dcol3=None, dcol4=None, dcol5=None,sinPs=None,
                    gamma=0.0, gam_steps=0.001, gp="n",
                    verbose=True):
        
        """
            Define rv baseline model parameters to fit.
            Each baseline model parameter should be a list of numbers specifying the polynomial order for each rv data.
            e.g. Given 3 input rvs, and one wishes to fit a 2nd order time trend to only the first and third lightcurves,
            then dt = [2, 0, 2].

            dt, dbis, dfwhm,dcont: list of ints;
                decorrelatation parameters: time, bis, fwhm, contrast
                
            gamma: tuple,floats or list of tuple/float;
                specify if to fit for gamma. if float/int, it is fixed to this value. If tuple of len 2 it assumes gaussian prior as (prior_mean, width).
        """

        if self._names == []: 
            if verbose: _print_output(self,"rv_baseline")
            return 
        
        if isinstance(gamma, list): assert len(gamma) == self._nRV, f"gamma must be type tuple/int or list of tuples/floats/ints of len {self._nRV}."
        elif isinstance(gamma, (tuple,float,int)): gamma=[gamma]*self._nRV
        else: _raise(TypeError, f"gamma must be type tuple/int or list of tuples/floats/ints of len {self._nRV}." )
        
        gammas,prior,gam_pri,sig_lo,sig_hi,bound_lo, bound_hi = [],[],[],[],[],[],[]
        for g in gamma:
            #fixed gammas
            if isinstance(g, (float,int)):
                prior.append("n")
                gammas.append(g)
                gam_pri.append(g)
                sig_lo.append(0)
                sig_hi.append(0)
                bound_lo.append(0)
                bound_hi.append(0)
            #fit gammas
            elif isinstance(g, tuple):
                if len(g)==2:
                    prior.append("y")
                    gammas.append(g[0])
                    gam_pri.append(g[0])
                    sig_lo.append(g[1])
                    sig_hi.append(g[1])  
                    bound_lo.append(g[0]-10*g[1])
                    bound_hi.append(g[0]+10*g[1])
                if len(g)==3:
                    prior.append("n")
                    gammas.append(g[1])
                    gam_pri.append(g[1])
                    sig_lo.append(0)
                    sig_hi.append(0)  
                    bound_lo.append(g[0])
                    bound_hi.append(g[2]) 

            else: _raise(TypeError, f"a tuple of len 2 or 3, float or int was expected but got the value {g} in gamma.")

        DA = locals().copy()     #get a dictionary of the input/variables arguments for easy manipulation
        _ = DA.pop("self")            #remove self from dictionary
        _ = [DA.pop(item) for item in ["verbose","gamma","g"]]


        for par in DA.keys():
            assert DA[par] is None or isinstance(DA[par], (int,float,str)) or (isinstance(DA[par], (list,np.ndarray)) and len(DA[par]) == self._nRV), f"parameter {par} must be a list of length {self._nRV} or int (if same degree is to be used for all RVs) or None (if not used in decorrelation)."
            
            if DA[par] is None: DA[par] = [0]*self._nRV
            elif isinstance(DA[par], (int,float,str)): DA[par] = [DA[par]]*self._nRV

            if par=="gp":
                for p in DA[par]: assert p in ["ce","y","n"], f"rv_baseline(): gp must be one of ['y','n'] but {p} given."
            

        self._RVbases = [ [DA["dcol0"][i], DA["dcol3"][i], DA["dcol4"][i], DA["dcol5"][i],DA["sinPs"][i]] for i in range(self._nRV) ]
        self._useGPrv = DA["gp"]
        self._gp_rvs  = lambda : np.array(self._names)[np.array(self._useGPrv) != "n"]     #lcs with gp == "y" or "ce"
        
        gampriloa=[]
        gamprihia=[]
        for i in range(self._nRV):
            gampriloa.append( 0. if (DA["prior"][i] == 'n' or DA["gam_steps"][i] == 0.) else DA["sig_lo"][i])
            gamprihia.append( 0. if (DA["prior"][i] == 'n' or DA["gam_steps"][i] == 0.) else DA["sig_hi"][i])
        
        DA["gampriloa"] = gampriloa                
        DA["gamprihia"] = gamprihia                
        
        self._rvdict   = DA
        if not hasattr(self,"_rvspline"):  self.add_spline(None, verbose=False)
        if np.all(np.array(self._useGPrv) == "n") or self._useGPrv==[]:        #if gp is "n" for all input lightcurves, run add_GP with None
            self.add_rvGP(None, verbose=False)

        if verbose: _print_output(self,"rv_baseline")
    

    def add_rvGP(self ,rv_list=None, par=[], kernel=[], operation=[""],
                    amplitude=[], lengthscale=[], verbose=True):
        """  
            Define GP parameters for each RV.
            The GP parameters, amplitude in RV unit  and lengthscale in unit of the desired column) can be defined in following ways:
            * fixed value as float or int, e.g amplitude = 2
            * free parameter with lognormal prior given as tuple of len 2, e.g. amplitude = (2, 1)
            * free parameters with loguniform prior interval and initial value given as tuple of length 3, e.g. amplitude = (1,2,5) with 2 being the initial value.
            
            Here the amplitude corresponds to the standard deviation of the noise process and the lengthscale corresponds to the characteristic timescale of the noise process.
            
            For the celerite sho kernel, the quality factor Q has been fixed to 1/sqrt(2) which is commonly used to model stellar oscillations/granulation noise (eqn 24 celerite paper).
            this lengthscale here is the undamped period of the oscillator.

            For the cosine kernel in George, lengthscale is the period. This kernel should probably always be multiplied by a stationary kernel (e.g. ExpSquaredKernel) to allow quasi-periodic variations.

            Parameters:
            -----------
            rv_list : str, list;
                list of rv files to add GP to. Default is None for no GP. if "all" is given, GP is added to all rv files where gp use has been indicated in ``rv_baseline()``. 
                If "same" is given, a global (same) GP is used for all indicated RV files in ``rv_baseline()``.
            par : str, tuple, list;
                column of the input data to use as the GP independent variable. a list is expected if different columns are to be used for the rv files given in rv_list.
                to use 2 different kernels on a single rv file, give column name for each kernel as a tuple of length 2. 
                e.g. rv_list=["rv1.dat","rv2.dat"], par = [("col0","col0"),"col3"] to use col0 for both kernels of rv1, and col3 for rv2.
            kernel : str, tuple, list;
                kernel to use for the GP. Must be one of ["mat32","mat52","exp","expsq","cos"] if George package is selected  and one of ["real","mat32","sho"] if using Celerite package
                A list is expected if different kernels are to be used for the rv files given in rv_list.
                to use 2 different kernels on a single rv file, give kernel name for each kernel as a tuple of length 2.
                e.g. rv_list=["rv1.dat","rv2.dat"], kernel = [("mat32","expsq"),"exp"] to use mat32 and expsq for rv1, and exp for rv2.
            operation : str, tuple, list;
                operation to combine 2 kernels. Must be one of ["+","*"]. Default is "" for no combination.
            amplitude : float, tuple, list;
                amplitude of the GP kernel. Must be int/float or tuple of length 2 or 3
            lengthscale : float, tuple, list;
                lengthscale of the GP kernel. Must be int/float or tuple of length 2 or 3
            verbose : bool;
                print output. Default is True.        
        """
        # supported 2-hyperparameter kernels
        george_allowed   = dict(kernels = ["mat32","mat52","exp","expsq","cos"],columns= ["col0","col3","col4","col5"])
        celerite_allowed = dict(kernels = ["real","mat32","sho"], columns=["col0"])

        self._rvGP_dict = {}
        self._sameRVgp  = SimpleNamespace(flag = False, first_index =None)

        if rv_list is None:
            if self._nRV>0:
                if len(self._gp_rvs())>0: print(f"\nWarning: GP was expected for the following rvs {self._gp_rvs()} \nMoving on ...")
                if verbose:_print_output(self,"rv_gp")
            return
        elif isinstance(rv_list, str):
            if rv_list == "same": 
                self._sameRVgp.flag        = True 
                self._sameRVgp.first_index = self._names.index(rv_list[0])
            if rv_list in ["all","same"]: 
                rv_list = self._gp_rvs()
            else: rv_list=[rv_list]


        for rv in self._gp_rvs(): assert rv in rv_list,f"add_rvGP(): GP was expected for {rv} but was not given in rv_list."
        for rv in rv_list: 
            assert rv in self._names,f"add_rvGP(): {rv} not in loaded rv files."
            assert rv in self._gp_rvs(),f"add_rvGP(): GP was not expected for {rv} but was given in rv_list."
        
        rv_ind = [self._names.index(rv) for rv in rv_list]
        gp_pck = [self._useGPrv[i] for i in rv_ind]   #gp_pck is a list of "y" or "ce" for each rv in rv_list

        DA = locals().copy()
        _  = [DA.pop(item) for item in ["self","verbose"]]

        for p in ["par","kernel","operation","amplitude","lengthscale"]:
            if isinstance(DA[p], (str,int,float,tuple)): DA[p] = [DA[p]]   #convert to list
            if isinstance(DA[p], list): 
                if self._sameRVgp.flag:    #ensure same inputs for all rvs with indicated gp
                    assert len(DA[p])==1, f"add_rvGP(): {p} must be a list of length {len(rv_list)} or length 1 (if same is to be used for all RVs)."
                DA[p] = DA[p]*len(rv_list)
            
            assert len(DA[p])==len(rv_list), f"add_rvGP(): {p} must be a list of length {len(rv_list)} or length 1 (if same is to be used for all RVs)."
            
        for p in ["par","kernel","operation","amplitude","lengthscale"]:
            #check if inputs for p are valid
            for i,list_item in enumerate(DA[p]):
                if p=="par":
                    if isinstance(list_item, str): 
                        if gp_pck[i]=="y":  assert list_item in george_allowed["columns"],  f'add_rvGP(): inputs of {p} must be in {george_allowed["columns"]}   but {list_item} given.'
                        if gp_pck[i]=="ce": assert list_item in celerite_allowed["columns"],f'add_rvGP(): inputs of {p} must be in {celerite_allowed["columns"]} but {list_item} given.'
                        DA["operation"][i] = ""
                    elif isinstance(list_item, tuple): 
                        assert len(list_item)==2,f'add_rvGP(): max of 2 gp kernels can be combined, but {list_item} given in {p}.'
                        assert DA["operation"][i] in ["+","*"],f'add_rvGP(): operation must be one of ["+","*"] to combine 2 kernels but {DA["operation"][i]} given.'
                        for tup_item in list_item: 
                            if gp_pck[i]=="y":  assert tup_item in george_allowed["columns"],  f'add_rvGP(): {p} must be in {george_allowed["columns"]}   but {tup_item} given.'
                            if gp_pck[i]=="ce": assert tup_item in celerite_allowed["columns"],f'add_rvGP(): {p} must be in {celerite_allowed["columns"]} but {tup_item} given.'
                        # assert that a tuple of length 2 is also given for kernels, amplitude and lengthscale.
                        for chk_p in ["kernel","amplitude","lengthscale"]:
                            assert isinstance(DA[chk_p][i], tuple) and len(DA[chk_p][i])==2,f'add_rvGP(): expected tuple of len 2 for {chk_p} element {i} but {DA[chk_p][i]} given.'
                            
                    else: _raise(TypeError, f"add_rvGP(): elements of {p} must be a tuple of length 2 or str but {list_item} given.")
                
                if p=="kernel":
                    if isinstance(list_item, str): 
                        if gp_pck[i]=="y":  assert list_item in george_allowed["kernels"],  f'add_rvGP(): {p} must be one of {george_allowed["kernels"]}   but {list_item} given.'
                        if gp_pck[i]=="ce": assert list_item in celerite_allowed["kernels"],f'add_rvGP(): {p} must be one of {celerite_allowed["kernels"]} but {list_item} given.'
                    elif isinstance(list_item, tuple):
                        for tup_item in list_item: 
                            if gp_pck[i]=="y":  assert tup_item in george_allowed["kernels"],  f'add_rvGP(): {p} must be one of {george_allowed["kernels"]}   but {tup_item} given.'
                            if gp_pck[i]=="ce": assert tup_item in celerite_allowed["kernels"],f'add_rvGP(): {p} must be one of {celerite_allowed["kernels"]} but {tup_item} given.'
                    else: _raise(TypeError, f"add_rvGP(): elements of {p} must be a tuple of length 2 or str but {list_item} given.")

                if p=="operation":
                    assert list_item in ["+","*",""],f'add_rvGP(): {p} must be one of ["+","*",""] but {list_item} given.'

                if p in ["amplitude", "lengthscale"]:
                    if isinstance(list_item, (int,float)): pass
                    elif isinstance(list_item, tuple):
                        if isinstance(DA["par"][i],tuple):
                            for tup in list_item:
                                if isinstance(tup, (int,float)): pass
                                elif isinstance(tup, tuple): 
                                    assert len(tup) in [2,3],f'add_rvGP(): {p} must be a float/int or tuple of length 2/3 but {tup} given.'
                                    if len(tup)==3: assert tup[0]<tup[1]<tup[2],f'add_rvGP(): uniform prior for {p} must follow (min, start, max) but {tup} given.'
                                else: _raise(TypeError, f"add_rvGP(): elements of {p} must be a tuple of length 23 or float/int but {tup} given.")
                        else:
                            assert len(list_item) in [2,3],f'add_rvGP(): {p} must be a float/int or tuple of length 2/3 but {tup} given.'
                            if len(list_item)==3: assert list_item[0]<list_item[1]<list_item[2],f'add_rvGP(): uniform prior for {p} must follow (min, start, max) but {list_item} given.'
                    else: _raise(TypeError, f"add_rvGP(): elements of {p} must be a tuple of length 2/3 or float/int but {list_item} given.")


        #setup parameter objects
        for i,rv in enumerate(rv_list):
            self._rvGP_dict[rv] = {}
            ngp = 2 if isinstance(DA["kernel"][i],tuple) else 1
            self._rvGP_dict[rv]["ngp"] = ngp
            self._rvGP_dict[rv]["op"]  = DA["operation"][i]

            for p in ["amplitude", "lengthscale"]:
                for j in range(ngp):
                    if ngp==1: 
                        v = DA[p][i]
                        this_kern, this_par = DA["kernel"][i], DA["par"][i]
                    else:
                        v = DA[p][i][j]
                        this_kern, this_par = DA["kernel"][i][j], DA["par"][i][j]

                    if isinstance(v, (int,float)):
                        self._rvGP_dict[rv][p+str(j)]     = _param_obj(to_fit="n", start_value=v,step_size=0,
                                                                        prior="n", prior_mean=v, prior_width_lo=0,
                                                                        prior_width_hi=0, bounds_lo=0.01, bounds_hi=0,
                                                                        user_data = [this_kern, this_par])
                    elif isinstance(v, tuple):
                        if len(v)==2:
                            steps = 0 if (self._sameRVgp.flag and i!=0) else 0.1*v[1]   #if sameRVgp is set, only first pars will jump and be used for all rvs
                            self._rvGP_dict[rv][p+str(j)] = _param_obj(to_fit="y", start_value=v[0],step_size=steps,prior="p", 
                                                                        prior_mean=v[0], prior_width_lo=v[1], prior_width_hi=v[1], 
                                                                        bounds_lo=v[0]-10*v[1], bounds_hi=v[0]+10*v[1],
                                                                        user_data=[this_kern, this_par])
                        elif len(v)==3:
                            steps = 0 if (self._sameRVgp.flag and i!=0) else min(0.001,0.001*np.ptp(v))
                            self._rvGP_dict[rv][p+str(j)] = _param_obj(to_fit="y", start_value=v[1],step_size=steps,
                                                                        prior="n", prior_mean=v[1], prior_width_lo=0,
                                                                        prior_width_hi=0, bounds_lo=v[0] if v[0]>0 else 0.007, bounds_hi=v[2],
                                                                        user_data=[this_kern, this_par])
                        #TODO add len(v)==4 for truncated normal (a,b,mu,std)
                    else: _raise(TypeError, f"add_rvGP(): elements of {p} must be a tuple of length 2/3 or float/int but {v} given.")

        if verbose: _print_output(self,"rv_gp")

    def add_custom_rvGP():
        NotImplementedError

    
    def add_spline(self, rv_list=None, par = None, degree=3, knot_spacing=None, verbose=True):
        """
            add spline to fit correlation along 1 or 2 columns of the data. This splits the data at the defined knots interval and fits a spline to each section. 
            scipy's LSQUnivariateSpline() and LSQBivariateSpline() functions are used for 1D spline and 2D splines respectively.
            All arguments can be given as a list to specify config for each rv file in rv_list.

            Parameters
            ----------
            rv_list : list, str, optional
                list of rv files to fit a spline to. set to "all" to use spline for all rv files. Default is None for no splines.

            par : str,tuple,list, optional
                column of input data to which to fit the spline. must be one/two of ["col0","col3","col4","col5"]. Default is None.
                Give list of columns if different for each rv file. e.g. ["col0","col3"] for spline in col0 for rv1.dat and col3 for rv2.dat. 
                For 2D spline for an rv file, use tuple of length 2. e.g. ("col0","col3") for simultaneous spline fit to col0 and col3.

            degree : int, tuple, list optional
                Degree of the smoothing spline. Must be 1 <= degree <= 5. Default is 3 for a cubic spline.
            
            knot_spacing : float, tuple, list
                distance between knots of the spline, by default 15 degrees for cheops data roll-angle 
            
            verbose : bool, optional
                print output. Default is True.

            Examples
            --------
            To use different spline configuration for 2 rv files: 2D spline for the first file and 1D for the second.
            >>> rv_obj.add_spline(rv_list=["rv1.dat","rv2.dat"], par=[("col3","col4"),"col4"], degree=[(3,3),2], knot_spacing=[(5,3),2])
            
            For same spline configuration for all loaded RV files
            >>> rv_obj.add_spline(rv_list="all", par="col3", degree=3, knot_spacing=5)
        """  
        #default spline config -- None
        self._rvspline = [None]*self._nRV                   #list to hold spline configuration for each rv
        for i in range(self._nRV):
            self._rvspline[i]        = SimpleNamespace()    #create empty namespace for each rv
            self._rvspline[i].name   = self._names[i]
            self._rvspline[i].dim    = 0
            self._rvspline[i].par    = None
            self._rvspline[i].use    = False
            self._rvspline[i].deg    = None
            self._rvspline[i].knots  = None
            self._rvspline[i].conf   = "None"

        if rv_list is None:
            if verbose: print("No spline\n")
            return
        elif rv_list == "all":
            rv_list = self._names
        else:
            if isinstance(rv_list, str): rv_list = [rv_list]
        
        nrv_spl = len(rv_list)   #number of rvs to add spline to
        for rv in rv_list:
            assert rv in self._names, f"add_spline(): {rv} not in loaded rv files: {self._names}."
        
        DA = locals().copy()
        _ = [DA.pop(item) for item in ["self", "verbose"]]  

        for p in ["par","degree","knot_spacing"]:
            if DA[p] is None: DA[p] = [None]*nrv_spl
            if isinstance(DA[p], (str,int,float,tuple)): DA[p] = [DA[p]]*nrv_spl
            if isinstance(DA[p], list): assert len(DA[p])==nrv_spl, f"add_spline(): {p} must be a list of length {nrv_spl} or length 1 (if same is to be used for all RVs)."
            
            #check if inputs are valid
            for list_item in DA[p]:
                if p=="par":
                    if isinstance(list_item, str): assert list_item in ["col0","col3","col4","col5",None],f'add_spline(): {p} must be in ["col0","col3","col4","col5"] but {list_item} given.'
                    if isinstance(list_item, tuple): 
                        for tup_item in list_item: assert tup_item in ["col0","col3","col4","col5",None],f'add_spline(): {p} must be in ["col0","col3","col4","col5"] but {tup_item} given.'
                if p=="degree": 
                    assert isinstance(list_item, (int,tuple)),f'add_spline(): {p} must be an integer but {list_item} given.'
                    if isinstance(list_item, tuple):
                        for tup_item in list_item: assert isinstance(tup_item, int),f'add_spline(): {p} must be an integer but {tup_item} given.'

        for i,rv in enumerate(rv_list):
            ind = self._names.index(rv)    #index of rv in self._names
            par, deg, knots =  DA["par"][i], DA["degree"][i], DA["knot_spacing"][i]
            dim = 1 if isinstance(par,str) else len(par)
            assert dim <=2, f"add_spline(): dimension of spline must be 1 or 2 but {par} (dim {dim}) given for {rv}."
            if dim==2:   #if 2d spline 
                if isinstance(deg, int): deg = (deg,deg)  #if degree is int, make it a tuple
                if isinstance(knots, int): knots = (knots,knots)

            self._rvspline[ind].name   = rv
            self._rvspline[ind].dim    = dim
            self._rvspline[ind].par    = par
            self._rvspline[ind].use    = True if par else False
            self._rvspline[ind].deg    = deg
            self._rvspline[ind].knots  = knots
            
            if dim==1:
                self._rvspline[ind].conf   = f"c{par[-1]}:d{deg}:k{knots}" if par else "None"
            else:
                self._rvspline[ind].conf   = f"c{par[0][-1]}:d{deg[0]}K{knots[0]}|c{par[1][-1]}:d{deg[1]}k{knots[1]}"

            if verbose: print(f"{rv} – Adding a degree {deg} spline to fit {par}: knot spacing= {knots}")
        
        if verbose: _print_output(self,"rv_baseline")
    
    def __repr__(self):
        data_type = str(self.__class__).split("load_")[1].split("'>")[0]
        self.print()
        if self._nRV>0:
            return f'{data_type} from filepath: {self._fpath}\n{self._nplanet} planet(s)\n'
        else:
            return ""
        
    def plot(self, plot_cols=(0,1,2), col_labels=None, nrow_ncols=None, figsize=None, fit_order=0, show_decorr_model=False,return_fig=False):
        """
            visualize data

            Parameters:
            -----------
            plot_cols : tuple of length 3;
                Tuple specifying which columns in input file to plot. 
                Default is (0,1,2) to plot time, flux with fluxerr. 
                Use (3,1,2) to show the correlation between the 4th column and the flux. 

            col_labels : tuple of length 2;
                label of the given columns in plot_cols. Default is ("time", "rv").

            nrow_ncols : tuple of length 2;
                Number of rows and columns to plot the input files. 
                Default is (None, None) to find the best layout.

            fit_order : int;
                order of polynomial to fit to the plotted data columns to visualize correlation.
                
            show_decorr_model : bool;
                show decorrelation model if decorrelation has been done.
            
            figsize: tuple of length 2;
                Figure size. If None, (8,5) is used for a single input file and optimally determined for more inputs.

            return_fig  : bool;
                return figure object for saving to file.
        """

        if not (isinstance(plot_cols, tuple) and len(plot_cols) in [2,3]): 
            raise TypeError(f"plot_cols must be tuple of length 2 or 3, but is {type(plot_cols)} and length of {len(plot_cols)}.")
        
        assert col_labels is None or ((isinstance(col_labels, tuple) and len(col_labels)==2)), \
            f"col_labels must be tuple of length 2, but is {type(col_labels)} and length of {len(col_labels)}."
        
        assert isinstance(fit_order,int),f'fit_order must be an integer'

        if show_decorr_model:
            if not hasattr(self,"_rvmodel"): 
                print("cannot show decorr model since decorrelation has not been done. First, use `rv_obj.get_decorr()` to launch decorrelation.")
                show_decorr_model = False
        
        if col_labels is None:
            col_labels = ("time", "rv") if plot_cols[:2] == (0,1) else (f"column[{plot_cols[0]}]",f"column[{plot_cols[1]}]")
        
        if self._names != []:
            fig = _plot_data(self, plot_cols=plot_cols, col_labels = col_labels, nrow_ncols=nrow_ncols, fit_order=fit_order, figsize=figsize,
                             model_overplot=self._rvmodel if show_decorr_model else None)
            if return_fig: return fig
        else: print("No data to plot")
    
    def print(self, section="rv_baseline"):
        _print_output(self, section)
    
class fit_setup:
    """
        class to configure mcmc run
            
        Parameters:
        ------------
        R_st, Mst : tuple of length 2 ;
            stellar radius and mass (in solar units) to use for calculating absolute dimensions.
            First tuple element is the value and the second is the uncertainty
        
        par_input : str;
            input method of stellar parameters. It can be one of  ["Rrho","Mrho"], to use the fitted stellar density and one stellar parameter (M_st or R_st) to compute the other stellar parameter (R_st or M_st).
            Default is 'Rrho' to use the fitted stellar density and stellar radius to compute the stellar mass.
            
        leastsq_for_basepar: "y" or "n";
            whether to use least-squares fit within the mcmc to fit for the baseline. This reduces +\
            the computation time especially in cases with several input files. Default is "n".

        apply_jitter: "y" or "n";
            whether to apply a jitter term for the fit of RV data. Default is "y".

        apply_LCjitter: "y" or "n";
        whether to apply a jitter term for the fit of LC data. Default is "y".

        LCbasecoeff_lims: list of length 2;
            limits of uniform prior for the LC baseline coefficients. Default is [-1,1].

        RVbasecoeff_lims: list of length 2;
            limits of uniform prior for the RV baseline coefficients. Default is [-2,2].
    
        Other keyword arguments to the emcee or dynesty sampler functions (`run_mcmc()` or `run_nested()`) can be given in the call to `CONAN3.fit_data`.
        
        Returns:
        --------
        fit_obj : fit object

        Examples:
        ---------
        >>> fit_obj = CONAN3.fit_setup(R_st=(1,0.01), M_st=(1,0.01), par_input="Rrho", apply_LCjitter="y", apply_RVjitter="y")
            fit_obj.sampling(sampler="emcee", ncpus=2,n_chains=64, n_steps=2000, n_burn=500)
    """

    def __init__(self, R_st=None, M_st=None, par_input = "Rrho",
                    apply_LCjitter="y", apply_RVjitter="y", leastsq_for_basepar="n",
                    LCbasecoeff_lims = [-1,1], RVbasecoeff_lims = [-2,2], verbose=True):
        
        self._obj_type = "fit_obj"
        self._stellar_parameters(R_st=R_st, M_st=M_st, par_input = par_input, verbose=verbose)
        
        DA = locals().copy()
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("verbose")
        
        self._fit_dict = DA

    def sampling(self, sampler="emcee", n_cpus=2,
                    n_chains=64, n_steps=2000, n_burn=500, emcee_move="stretch",  
                    n_live=300, dyn_dlogz=0.1, verbose=True,  
                    apply_CFs="y",remove_param_for_CNM="n", lssq_use_Lev_Marq="n",
                    GR_test="y", make_plots="n", leastsq="y", savefile="output_ex1.npy",
                    savemodel="n", adapt_base_stepsize="y"):
        """   
        configure sampling

        Parameters:
        -----------

        sampler: str;
            sampler to use. Default is "emcee". Options are ["emcee","dynesty"].
        
        n_cpus: int;
            number of cpus to use for parallelization.
            
        n_chains: int;
            number of chains/walkers
        
        n_steps: int;
            length of each chain. the effective total steps becomes n_steps*n_chains.

        n_burn: int;
            number of steps to discard as burn-in

        emcee_move: str;
            sampler algorithm to use in traversing the parameter space. Options are ["demc","snooker",stretch].
            The default is stretch to use the emcee StretchMove.

        n_live: int;
            number of live points to use for dynesty sampler. Default is 300.

        dyn_dlogz: float;
            stopping criterion for dynesty sampler. Default is 0.1.

        verbose: bool;
            print output. Default is True.
        """

        assert sampler in ["emcee","dynesty"],f'sampler must be one of ["emcee","dynesty"] but {sampler} given.'
        assert emcee_move in ["demc","snooker","stretch"],f'emcee_move must be one of ["demc","snooker","stretch] but {emcee_move} given.'
        
        DA = _reversed_dict(locals().copy())
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("verbose")
        self._obj_type = "fit_obj"
        self._fit_dict.update(DA)

        if verbose: _print_output(self,"fit")

    def _stellar_parameters(self,R_st=None, M_st=None, par_input = "Rrho", verbose=True):
        """
            input parameters of the star

            Parameters:
            -----------
            R_st, Mst : tuple of length 2 or 3;
                stellar radius and mass (in solar units) to use for calculating absolute dimensions.
                First tuple element is the value and the second is the uncertainty. use a third element if asymmetric uncertainty
            
            par_input : str;
                input method of stellar parameters. It can be one of  ["Rrho","Mrho"], to use the fitted stellar density and one stellar parameter (M_st or R_st) to compute the other stellar parameter (R_st or M_st).
                Default is 'Rrho' to use the fitted stellar density and stellar radius to compute the stellar mass.
        """

        DA = locals().copy()
        _ = DA.pop("self")            #remove self from dictionary
        _ = DA.pop("verbose")
        
        for par in ["R_st", "M_st"]:
            assert DA[par] is None or isinstance(DA[par],tuple), f"stellar_parameters: {par} must be either None or tuple of length 2 "
            if DA[par] is None: DA[par] = (1,0.01)
            elif isinstance(DA[par],tuple):
                assert len(DA[par])==2, f"stellar_parameters(): length of {par} tuple must be 2"
                DA[par]= (DA[par][0], DA[par][1], DA[par][1])
            else: _raise(TypeError, f"stellar_parameters(): {par} must be either None or tuple of length 2 but {DA[par]} given.")
        
        assert DA["par_input"] in ["Rrho","Mrho"], f"stellar_parameters: par_input must be one of ['Rrho','Mrho']."
        self._stellar_dict = DA

        if verbose: _print_output(self,"stellar_pars")

    def __repr__(self):
        if self._fit_dict['sampler'] == "emcee":
            return f"Sampling setup:\n  sampler: {self._fit_dict['sampler']}\n  steps: {self._fit_dict['n_steps']}\n  chains: {self._fit_dict['n_chains']}"
        else:
            return f"Sampling setup:\n  sampler: {self._fit_dict['sampler']}\n  live points: {self._fit_dict['n_live']}\n  dlogz: {self._fit_dict['dyn_dlogz']}"

    def print(self, section="fit"):
        if section == "all":
            _print_output(self,"stellar_pars")
            _print_output(self,"fit")
        else:
            _print_output(self, section)


class load_result:
    """
        Load results from mcmc run
        
        Parameters:
        ------------
        folder: str;
            folder where the output files are located. Default is "output".
        
        chain_file: str;
            name of the file containing the chains. Default is "chains_dict.pkl".
        
        burnin_chain_file: str;
            name of the file containing the burn-in chains. Default is "burnin_chains_dict.pkl".

        Returns:
        --------
        load_result : load_result object

        Examples:
        ---------
        >>> result = CONAN3.load_result(folder="output")
    """

    def __init__(self, folder="output",chain_file = "chains_dict.pkl", burnin_chain_file="burnin_chains_dict.pkl",verbose=True):

        chain_file        = folder+"/"+chain_file
        burnin_chain_file = folder+"/"+burnin_chain_file
        self._folder = folder
        assert os.path.exists(chain_file) or os.path.exists(burnin_chain_file) , f"file {chain_file} or {burnin_chain_file}  does not exist in the given directory"

        if os.path.exists(chain_file):
            self._chains = pickle.load(open(chain_file,"rb"))
        if os.path.exists(burnin_chain_file):
            self._burnin_chains = pickle.load(open(burnin_chain_file,"rb"))

        self._par_names     = self._chains.keys() if os.path.exists(chain_file) else self._burnin_chains.keys()
        self.params_names   = list(self._par_names)

        #retrieve summary statistics of the fit
        self._ind_para      = pickle.load(open(folder+"/.par_config.pkl","rb"))
        self.fit_sampler    = self._ind_para[71]

        #reconstruct posterior from dictionary of chains
        if hasattr(self,"_chains"):
            if self.fit_sampler=="emcee":
                posterior = np.array([ch for k,ch in self._chains.items()])
                posterior = np.moveaxis(posterior,0,-1)
                s = posterior.shape
                self.flat_posterior = posterior.reshape((s[0]*s[1],s[2])) #FLATTEN posterior
            else:
                self.flat_posterior = np.array([ch for k,ch in self._chains.items()]).T

            try:
                self._stat_vals     = pickle.load(open(folder+"/.stat_vals.pkl","rb"))
                self.params_median  = self._stat_vals["med"]
                self.params_max     = self._stat_vals["max"]
                self.params_bestfit = self._stat_vals["bf"]
            except:
                self.params_median  = np.median(self.flat_posterior,axis=0)
            
            self.params_bfdict  = {k:v for k,v in zip(self.params_names, self.params_median)}
            self.lc             = SimpleNamespace(  names    = self._ind_para[31],
                                                    filters  = self._ind_para[12],
                                                    evaluate = self._evaluate_lc,
                                                    outdata  = self.load_result_array(["lc"],verbose=verbose),
                                                    indata   = None)
            self.rv             = SimpleNamespace(  names    = self._ind_para[32],
                                                    filters  = self._ind_para[12],
                                                    evaluate = self._evaluate_rv,
                                                    outdata  = self.load_result_array(["rv"],verbose=verbose),
                                                    indata   = None)

        

    def __repr__(self):
        return f'Object containing chains (main or burn-in) from mcmc. \
                \nParameters in chain are:\n\t {self.params_names} \
                \n\nuse `plot_chains()`, `plot_burnin_chains()`, `plot_corner()` or `plot_posterior()` methods on selected parameters to visualize results.'
        
    def plot_chains(self, pars=None, figsize = None, thin=1, discard=0, alpha=0.05,
                    color=None, label_size=12, force_plot = False):
        """
            Plot chains of selected parameters.
              
            Parameters:
            ------------
            pars: list of str;
                parameter names to plot. Plot less than 20 parameters at a time for clarity.

            figsize: tuple of length 2;
                Figure size. If None, optimally determined.
        
            thin : int;
                factor by which to thin the chains in order to reduce correlation.

            discard : int;
                to discard first couple of steps within the chains. 

            alpha : float;
                transparency of the lines in the plot.

            color : str;
                color of the lines in the plot.

            label_size : int;
                size of the labels in the plot.

            force_plot : bool;
                if True, plot more than 20 parameters at a time.
        """
        if self.fit_sampler=="dynesty":
            print("chains are not available for dynesty sampler")
            return
        
        assert pars is None or isinstance(pars, list) or pars == "all", \
             f'pars must be None, "all", or list of relevant parameters.'
        if pars is None or pars == "all": pars = [p for p in self._par_names]
        for p in pars:
            assert p in self._par_names, f'{p} is not one of the parameter labels in the mcmc run.'
        
        ndim = len(pars)
        if not force_plot: assert ndim < 21, f'number of parameter chain to plot should be <=20 for clarity. Use force_plot = True to continue anyways.'

        if figsize is None: figsize = (12,6+int(ndim/2))
        fig, axes = plt.subplots(ndim, sharex=True, figsize=figsize)
        if ndim == 1: axes = np.array([axes])
            
        if thin > 1 and discard > 0:
            axes[0].set_title(f"Discarded first {discard} steps & thinned by {thin}", fontsize=14)
        elif thin > 1 and discard == 0:
            axes[0].set_title(f"Thinned by {thin}", fontsize=14)
        else:
            axes[0].set_title(f"Discarded first {discard} steps", fontsize=14)
            
        
        for i,p in enumerate(pars):
            ax = axes[i]
            ax.plot(self._chains[p][:,discard::thin].T,c = color, alpha=alpha)
            ax.legend([pars[i]],loc="upper left")
            ax.autoscale(enable=True, axis='x', tight=True)
        plt.subplots_adjust(hspace=0.0)
        axes[-1].set_xlabel("step number", fontsize=label_size);

        return fig

            
    def plot_burnin_chains(self, pars=None, figsize = None, thin=1, discard=0, alpha=0.05,
                    color=None, label_size=12, force_plot = False):
        """
            Plot chains of selected parameters.
            
            Parameters:
            ------------
            pars: list of str;
                parameter names to plot. Plot less than 20 parameters at a time for clarity.
        
            thin : int;
                factor by which to thin the chains in order to reduce correlation.

            discard : int;
                to discard first couple of steps within the chains. 
        
        """
        if self.fit_sampler=="dynesty":
            print("chains are not available for dynesty sampler")
            return
        self._par_names = self._burnin_chains.keys()
        assert pars is None or isinstance(pars, list) or pars == "all", \
            f'pars must be None, "all", or list of relevant parameters.'
        if pars is None or pars == "all": pars = [p for p in self._par_names]
        for p in pars:
            assert p in self._par_names, f'{p} is not one of the parameter labels in the mcmc run.'
        
        ndim = len(pars)
        if not force_plot: assert ndim < 21, f'number of parameter chain to plot should be <=20 for clarity. Use force_plot = True to continue anyways.'

        if figsize is None: figsize = (12,6+int(ndim/2))
        fig, axes = plt.subplots(ndim, sharex=True, figsize=figsize)
        if ndim == 1: axes = np.array([axes])
            
        if thin > 1 and discard > 0:
            axes[0].set_title(f"Burn-in\nDiscarded first {discard} steps & thinned by {thin}", fontsize=14)
        elif thin > 1 and discard == 0:
            axes[0].set_title(f"Burn-in\nThinned by {thin}", fontsize=14)
        else:
            axes[0].set_title(f"Burn-in\nDiscarded first {discard} steps", fontsize=14)
            
        
        for i,p in enumerate(pars):
            ax = axes[i]
            ax.plot(self._burnin_chains[p][:,discard::thin].T,c = color, alpha=alpha)
            ax.legend([pars[i]],loc="upper left")
            ax.autoscale(enable=True, axis='x', tight=True)
        plt.subplots_adjust(hspace=0.0)
        axes[-1].set_xlabel("step number", fontsize=label_size);

        return fig
        
    def plot_corner(self, pars=None, bins=20, thin=1, discard=0,
                    q=[0.16,0.5,0.84], range=None,show_titles=True, title_fmt =".3f", titlesize=14,
                    labelsize=20, multiply_by=1, add_value= 0, force_plot = False ):
        """
            Corner plot of selected parameters.
            
            Parameters:
            ------------
            pars : list of str;
                parameter names to plot. Ideally less than 14 pars for clarity of plot

            bins : int;
                number of bins in 1d histogram

            thin : int;
                factor by which to thin the chains in order to reduce correlation.

            discard : int;
                to discard first couple of steps within the chains. 
            
            q : list of floats;
                quantiles to show on the 1d histograms. defaults correspoind to +/-1 sigma
                
            range : iterable (same length as pars);
                A list where each element is either a length 2 tuple containing
                lower and upper bounds or a float in range (0., 1.)
                giving the fraction of samples to include in bounds, e.g.,
                [(0.,10.), (1.,5), 0.999, etc.].
                If a fraction, the bounds are chosen to be equal-tailed.
        """
        assert pars is None or isinstance(pars, list) or pars == "all", \
             f'pars must be None, "all", or list of relevant parameters.'
        if pars is None or pars == "all": pars = [p for p in self._par_names]

        ndim = len(pars)

        if not force_plot: assert ndim <= 14, \
            f'number of parameters to plot should be <=14 for clarity. Use force_plot = True to continue anyways.'

        lsamp = len(self._chains[pars[0]][:,discard::thin].flatten()) if self.fit_sampler=="emcee" else len(self._chains[pars[0]])
        samples = np.empty((lsamp,ndim))

        #adjustments to make values more readable
        if isinstance(multiply_by, (int,float)): multiply_by = [multiply_by]*ndim
        elif isinstance(multiply_by, list): assert len(multiply_by) == ndim
        if isinstance(add_value, (int,float)): add_value = [add_value]*ndim
        elif isinstance(add_value, list): assert len(add_value) == ndim


        for i,p in enumerate(pars):
            assert p in self._par_names, f'{p} is not one of the parameter labels in the mcmc run.'
            if self.fit_sampler=="emcee":
                samples[:,i] = self._chains[p][:,discard::thin].reshape(-1) * multiply_by[i] + add_value[i]
            else:
                samples[:,i] = self._chains[p]
        
        fig = corner.corner(samples, bins=bins, labels=pars, show_titles=show_titles, range=range,
                    title_fmt=title_fmt,quantiles=q,title_kwargs={"fontsize": titlesize},
                    label_kwargs={"fontsize":labelsize})
        
        return fig


    def plot_posterior(self, par, thin=1, discard=0, bins=20, density=True, range=None,
                        q = [0.0015,0.16,0.5,0.85,0.9985], multiply_by=1, add_value=0, 
                        return_values=False):
        """
        Plot the posterior distribution of a single input parameter, par.
        if return_values = True, the summary statistic for the parameter is also returned as an output.  

        Parameters:
        -----------
        par : str;
            parameter posterior to plot

        thin : int;
            thin samples by factor of 'thin'

        discard : int;
            to discard first couple of steps within the chains. 


        Returns:
        --------
        fig: figure object

        result: tuple of len 3;
            summary statistic for the parameter, par, in the order [median, -1sigma, +1sigma] 

        """
        assert isinstance(par, str), 'par must be a single parameter of type str'
        assert par in self._par_names, f'{par} is not one of the parameter labels in the mcmc run.'
        assert isinstance(q, (float, list)),"q must be either a single float or list of length 1, 3 or 5"
        if isinstance(q,float): q = [q]
        
        if self.fit_sampler=="emcee":
            par_samples = self._chains[par][:,discard::thin].flatten() * multiply_by + add_value
        else:
            par_samples = self._chains[par] * multiply_by + add_value

        quants = np.quantile(par_samples,q)

        if len(q)==1:
            ls = ['-']; c=["r"]
            med = quants[0]
        elif len(q)==3: 
            ls = ["--","-","--"]; c = ["r"]*3 
            med = quants[1]; sigma_1 = np.diff(quants)
        elif len(q)==5: 
            ls = ["--","--","-","--","--"]; c =["k",*["r"]*3,"k"] 
            med=quants[2]; sigma_1 = np.diff(quants[1:4])
        else: _raise(ValueError, "q must be either a single float or list of length 1, 3 or 5")

        fig  = plt.figure()
        plt.hist(par_samples, bins=bins, density=density, range=range);
        [plt.axvline(quants[i], ls = ls[i], c=c[i], zorder=3) for i in np.arange(len(quants))]
        if len(q)==1:
            plt.title(f"{par}={med:.4f}")
        else:
            plt.title(f"{par}={med:.4f}$^{{+{sigma_1[1]:.4f}}}_{{-{sigma_1[0]:.4f}}}$")

        plt.xlabel(par);

        if return_values:
            result = [med, sigma_1[0],sigma_1[1]]
            return fig, result

        return fig


    def load_result_array(self, data=["lc","rv"],verbose=True):
        """
            Load result array from CONAN3 fit allowing for customised plots.
            All files with '_**out.dat' are loaded. 

            Returns:
            --------
                results : dict;
                    dictionary of holding the arrays for each output file.
                
            Examples
            --------
            >>> import CONAN3
            >>> res=CONAN3.load_result()
            >>> results = res.load_result_array()
            >>> list(results.keys())
            ['lc8det_lcout.dat', 'lc6bjd_lcout.dat']

            >>> df1 = results['lc8det_lcout.dat']
            >>> df1.keys()
            ['time', 'flux', 'error', 'full_mod', 'gp*base', 'transit', 'det_flux']

            >>> #plot arrays
            >>> plt.plot(df["time"], df["flux"],"b.")
            >>> plt.plot(df["time"], df["gp*base"],"r")
            >>> plt.plot(df["time"], df["transit"],"g")
            
        """
        out_files_lc = sorted([ f  for f in os.listdir(self._folder) if '_lcout.dat' in f])
        out_files_rv = sorted([ f  for f in os.listdir(self._folder) if '_rvout.dat' in f])
        all_files    = []
        if "lc" in data: all_files.extend(out_files_lc)
        if "rv" in data: all_files.extend(out_files_rv)
        
        results = {}
        for f in all_files:
            df = pd.read_fwf(self._folder+"/"+f, header=0)
            df = df.rename(columns={'# time': 'time'})
            keyname = f[:-10]+f[-4:]   #remove _rvout or _lcout from filename
            results[keyname] = df
        if verbose: print(f"{data} Output files, {all_files}, loaded into result object")
        return results

    def make_output_file(self, stat="median"):
        """
        make output model file ("*_??out.dat") from parameters obtained using different summary statistic on the posterior.
        if a *_??out.dat file already exists, it is overwritten (so be sure!!!).

        Parameters
        ----------
        stat : str, optional
            posterior summary statistic to use for model calculation, must be one of ["median","max","bestfit"], by default "median".
            "max" and "median" calculate the maximum and median of each parameter posterior respectively while "bestfit" \
            is the parameter combination that gives the maximum joint posterior probability.
        """
        
        from CONAN3.logprob_multi_sin_v4 import logprob_multi
        from CONAN3.plots_v12 import mcmc_plots

        assert stat in ["median","max","bestfit"],f'make_output_file: stat must be of ["median","max","bestfit"] but {stat} given'
        if   stat == "median":  stat = "med"
        elif stat == "bestfit": stat = "bf"

        mval2, merr2, T0_post, p_post = logprob_multi(self._stat_vals[stat],*self._ind_para,make_outfile=True, verbose=True)

        return
        
    def _evaluate_lc(self, file, time=None,params=None, nsamp=5000,return_std=False, return_components=False):
        """
        Compute transit model from CONAN3 fit for a given input file at the given times using specified parameters.

        Parameters:
        -----------
        file : str;
            name of the LC file  for which to evaluate the LC model.

        time : array-like;
            times at which to evaluate the model

        params : array-like;
            parameters to evaluate the model at. The median posterior parameters from the fit are used if params is None

        nsamp : int;
            number of posterior samples to use for computing the 1sigma quantiles of the model. Default is 5000.

        return_std : bool;
            if True, return the 1sigma quantiles of the model as well as the model itself. If False, return only the model.

        return_components : bool;
            if True, return transit model for each planet in the system. If False, return only the total lc model.

        Returns:
        --------
        lcmodel, lc_comps, 1sigma_lo, 1sigma_hi : array, dict, array, array,  respectively;
            Transit model array evaluated at the given times, for a specific file. transit_components are return if return_components is True.
            if return_std is True, 1sigma quantiles (lo and hi) of the model is returned.
        """

        from CONAN3.logprob_multi_sin_v4 import logprob_multi
        
        if params is None: params = self.params_median
        mod  = logprob_multi(params,*self._ind_para,t=time,get_model=True)
        keys = mod.lc.keys() 

        if not return_std:    #return only the model
            return mod.lc[file] if return_components else mod.lc[file][0]
        else:                 #return model and quantiles
            lenpost = len(self.flat_posterior)
            mods    = []  #store model realization for each parameter combination

            for p in self.flat_posterior[np.random.randint(0,lenpost,int(min(nsamp,0.2*lenpost)))]:   #at most 5000 random posterior samples 
                temp = logprob_multi(p,*self._ind_para,t=time,get_model=True)
                mods.append(temp.lc[file][0])

            qs = np.quantile(mods,q=[0.16,0.5,0.84],axis=0) #compute 68% percentiles

            return (mod.lc[file][0],mod.lc[file][1],qs[0],qs[1]) if return_components else (mod.lc[file][0],qs[0],qs[1])
        
    def _evaluate_rv(self, file, time=None,params=None, nsamp=5000,return_std=False, return_components=False):
        """
        Compute RV model from CONAN3 fit for a given input file at the given times using specified parameters.

        Parameters:
        -----------
        file : str;
            name of the RV file for which to evaluate the RVmodel.

        time : array-like;
            times at which to evaluate the model

        params : array-like;
            parameters to evaluate the model at. The median posterior parameters from the fit are used if params is None

        nsamp : int;    
            number of posterior samples to use for computing the 1sigma quantiles of the model. Default is 5000.

        return_std : bool;
            if True, return the 1sigma quantiles of the model as well as the model itself. If False, return only the model.

        return_components : bool;
            if True, return rv model for each planet in the system. If False, return only the total rv model.

        Returns:
        --------
        rvmodel, rv_comps, 1sigma_lo, 1sigma_hi : array, dict, array, array,  respectively;
            RV model array evaluated at the given times, for a specific file. rv_components are return if return_components is True.
            if return_std is True, 1sigma quantiles (lo and hi) of the model is returned.
        """

        from CONAN3.logprob_multi_sin_v4 import logprob_multi

        if params is None: params = self.params_median
        mod  = logprob_multi(params,*self._ind_para,t=time,get_model=True)

        if not return_std:     #return only the model
            return mod.rv[file] if return_components else mod.rv[file][0]
        else:                 #return model and quantiles
            lenpost = len(self.flat_posterior)
            mods    = []

            for p in self.flat_posterior[np.random.randint(0,lenpost,int(min(5000,0.2*lenpost)))]:   #at most 5000 random posterior samples
                temp = logprob_multi(p,*self._ind_para,t=time,get_model=True)
                mods.append(temp.rv[file][0])

            qs = np.quantile(mods,q=[0.16,0.5,0.84],axis=0) #compute 68% percentiles
            
            return (mod.rv[file][0],mod.rv[file][1],qs[0],qs[1]) if return_components else (mod.rv[file][0],qs[0],qs[1])



def create_configfile(lc_obj, rv_obj, fit_obj, filename="input_config.dat"): 
    """
        create configuration file that of lc_obj, rv_obj, amd fit_obj setup.
        
        Parameters:
        -----------
        lc_obj : object;
            Instance of CONAN.load_lightcurve() object and its attributes.

        rv_obj : object, None;
            Instance of CONAN.load_rvs() object and its attributes.
        
        fit_obj : object;
            Instance of CONAN.fit_setup() object and its attributes.
    """
    f = open(filename,"w")
    f.write("# ========================================== CONAN configuration file ============================================= \n")
    f.write("#             *********** KEYS *****************************************************************************************\n")
    f.write("#             PRIORS: *Fixed - F(val), *Normal - N(mu,std), *Uniform - U(min,start,max), *LogUniform - LU(min,start,max)\n")
    f.write("#             s_samp: supersampling - x{exp_time}\n")
    f.write("#             clip:   clip outliers - W{window_width}C{clip_sigma}\n")
    f.write("#             spline_config: spline - c{column_no}:d{degree}K{knot_spacing}\n")
    f.write("#             ***********************************************************************************************************\n")
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    f.write(f"LC_filepath: {lc_obj._fpath}\n")
    f.write(f"RV_filepath: {lc_obj._fpath}\n")
    f.write(f"n_planet: {lc_obj._nplanet}\n")
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(lc_obj,"lc_baseline",file=f)
    _print_output(lc_obj,"gp",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(rv_obj,"rv_baseline",file=f)
    _print_output(rv_obj,"rv_gp",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(lc_obj,"planet_parameters",file=f)
    _print_output(lc_obj,"limb_darkening",file=f)
    _print_output(lc_obj,"depth_variation",file=f)
    _print_output(lc_obj,"phasecurve",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(lc_obj,"contamination",file=f)
    _print_output(fit_obj,"stellar_pars",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(fit_obj, "fit",file=f)
    f.close()


def load_configfile(configfile="input_config.dat", return_fit=False, verbose=True):
    """
        configure conan from specified configfile.
        
        Parameters:
        -----------
        configfile: filepath;
            path to configuration file.

        return_fit: bool;
            whether to immediately perform the fit from this function call.
            if True, the result object from the fit is also returned

        verbose: bool;
            show print statements

        Returns:
        --------
        lc_obj, rv_obj, fit_obj. if return_fit is True, the result object of fit is also returned

        lc_obj: object;
            light curve data object generated from `conan3.load_lighturves()`.
        
        rv_obj: object;
            rv data object generated from `conan3.load_rvs()`
            
        fit_obj: object;
            fitting object generated from `conan3.fit_setup()`.

        result: object;
            result object containing chains of the mcmc fit.
    
    """

    def _prior_value(str_prior): 
        "convert string prior into float/tuple"
        str_prior = str_prior[str_prior.find("(")+1:str_prior.find(")")].split(",")
        tuple_prior = [float(v) for v in str_prior]
        tuple_prior = [(int(v) if v.is_integer() else float(v)) for v in tuple_prior]
        len_tup = len(tuple_prior)
        val = tuple_prior[0] if len_tup==1 else tuple(tuple_prior)
        return val


    _file = open(configfile,"r")
    _skip_lines(_file,8)                       #remove first 2 comment lines
    fpath    = _file.readline().rstrip().split()[1]           # the path where the files are
    rv_fpath = _file.readline().rstrip().split()[1]           # the path where the files are
    nplanet  = int(_file.readline().rstrip().split()[1])      # the path where the files are
    _skip_lines(_file,3)                                      #remove 3 comment lines

    # ========== Lightcurve input ====================
    _names=[]                    # array where the LC filenames are supposed to go
    _filters=[]                  # array where the filter names are supposed to go
    _lamdas=[]
    _bases=[]                    # array where the baseline exponents are supposed to go
    _groups=[]                   # array where the group indices are supposed to go
    _grbases=[]
    _useGPphot=[]
    
    _ss_lclist,_ss_exp = [],[]
    _clip_lclist, _clip, _clip_width  = [],[],[]
    _sclcol= []
    _spl_lclist,_spl_deg,_spl_par, _spl_knot=[],[],[],[]
    
    #read baseline specification for each listed light-curve file 
    dump = _file.readline() 
    while dump[0] != '#':                   # if it is not starting with # then
        _adump = dump.split()               # split it

        _names.append(_adump[0])            # append the first field to the name array
        _filters.append(_adump[1])          # append the second field to the filters array
        _lamdas.append(float(_adump[2]))    # append the second field to the filters array
        
        #supersample
        xt = _adump[3].split("|")[-1]
        if xt != "None":
            _ss_lclist.append(_adump[0])
            _ss_exp.append(float(xt.split("x")[1]))
        
        #clip_outlier
        if _adump[4]!= "None":
            _clip_lclist.append(_adump[0])
            clip_v = float(_adump[4].split("C")[1]) 
            _clip.append(int(clip_v) if clip_v.is_integer() else clip_v)                   # outlier clip value
            _clip_width.append(int(_adump[4].split("C")[0].split("W")[1])) # windown width
    
        _sclcol.append(_adump[5].split("|")[0])

        strbase=_adump[6:11]
        strbase.append(_adump[11].split("|")[0])        # string array of the baseline function coeffs
        grbase = 0
        strbase.extend([_adump[12],grbase])
        _grbases.append(grbase)
        base = [int(i) for i in strbase]
        _bases.append(base)
        
        group = int(_adump[13])
        _groups.append(group)
        _useGPphot.append(_adump[14])
        
        #LC spline
        if _adump[15] != "None":
            _spl_lclist.append(_adump[0])
            _spl_knot.append(float(_adump[15].split("k")[-1]))
            _spl_deg.append(int(_adump[15].split("k")[0].split("d")[-1]))
            _spl_par.append("col" + _adump[15].split("k")[0].split("d")[0][1])

        #move to next LC
        dump =_file.readline() 

    _skip_lines(_file,1)                                      #remove 1 comment lines
    
    # ========== GP input ====================
    gp_lclist,op = [],[]
    gp_pars, kernels, amplitude, lengthscale = [],[],[],[]

    dump =_file.readline()
    while dump[0] != "#":
        _adump = dump.split()
        gp_lclist.append(_adump[0])
        gp_pars.append(_adump[1])
        kernels.append(_adump[2])
        amplitude.append(_prior_value(_adump[3]))
        lengthscale.append(_prior_value(_adump[4]))
        
        op.append(_adump[5].strip("|"))
        if op[-1] != "--":    #if theres a second kernel 
            gp_pars[-1]     = (gp_pars[-1],_adump[6])
            kernels[-1]     = (kernels[-1],_adump[7])
            amplitude[-1]   = (amplitude[-1],_prior_value(_adump[8]))
            lengthscale[-1] = (lengthscale[-1],_prior_value(_adump[9]))

        #move to next LC
        dump =_file.readline()
    _skip_lines(_file,2)  
    
    
    # instantiate light curve object
    lc_obj = load_lightcurves(_names, fpath, _filters, _lamdas, nplanet)
    lc_obj.lc_baseline(*np.array(_bases).T, grp_id=_groups, gp=_useGPphot,verbose=False )
    lc_obj.clip_outliers(lc_list=_clip_lclist, clip=_clip, width=_clip_width,show_plot=False,verbose=False )
    if _sclcol[0] != "None": 
        lc_obj.rescale_data_columns(method=_sclcol[0],verbose=False)
    lc_obj.supersample(lc_list=_ss_lclist, exp_time=_ss_exp, verbose=False)
    lc_obj.add_spline(lc_list=_spl_lclist ,par=_spl_par , degree=_spl_deg,
                        knot_spacing=_spl_knot , verbose=False)
    if verbose: lc_obj.print("lc_baseline")
    lc_obj.add_GP(lc_list=gp_lclist,par=gp_pars,kernel=kernels,operation="op",
                    amplitude=amplitude,lengthscale=lengthscale,verbose=verbose)
    
    ## RV ==========================================================
    RVnames, RVbases, gammas = [],[],[]
    _RVsclcol, usegpRV,strbase = [],[],[]
    _spl_rvlist,_spl_deg,_spl_par, _spl_knot=[],[],[],[]
    
    dump =_file.readline()
    while dump[0] != '#':                   # if it is not starting with # then
        _adump = dump.split()               # split it
        RVnames.append(_adump[0])
        _RVsclcol.append(_adump[1])
        strbase=_adump[3:6]                  # string array of the baseline function coeffs
        strbase.append(_adump[6].split("|")[0])
        strbase.append(_adump[7])
        base = [int(i) for i in strbase]
        RVbases.append(base)
        usegpRV.append(_adump[8])
        
        #RV spline
        if _adump[9] != "None":
            _spl_rvlist.append(_adump[0])
            _spl_knot.append(float(_adump[9].split("k")[-1]))
            _spl_deg.append(int(_adump[9].split("k")[0].split("d")[-1]))
            _spl_par.append("col" + _adump[9].split("k")[0].split("d")[0][1])
        
        gammas.append(_prior_value(_adump[11]))
        #move to next RV
        dump =_file.readline()

    _skip_lines(_file,1)                                      #remove 1 comment lines
    
    # RV GP
    gp_rvlist,op = [],[]
    gp_pars, kernels, amplitude, lengthscale = [],[],[],[]

    dump =_file.readline()
    while dump[0] != "#":
        _adump = dump.split()
        gp_rvlist.append(_adump[0])
        gp_pars.append(_adump[1])
        kernels.append(_adump[2])
        amplitude.append(_prior_value(_adump[3]))
        lengthscale.append(_prior_value(_adump[4]))
        
        op.append(_adump[5].strip("|"))
        if op[-1] != "––":    #if theres a second kernel 
            gp_pars[-1]     = (gp_pars[-1],_adump[6])
            kernels[-1]     = (kernels[-1],_adump[7])
            amplitude[-1]   = (amplitude[-1],_prior_value(_adump[8]))
            lengthscale[-1] = (lengthscale[-1],_prior_value(_adump[9]))

        #move to next LC
        dump =_file.readline()
        
        
    rv_obj = load_rvs(RVnames,rv_fpath, nplanet=nplanet,lc_obj=lc_obj)
    rv_obj.rv_baseline(*np.array(RVbases).T, gamma=gammas,gp=usegpRV,verbose=verbose) 
    if _RVsclcol[0] != "None":
        rv_obj.rescale_data_columns(method=_RVsclcol[0],verbose=False)
    rv_obj.add_spline(rv_list=_spl_rvlist ,par=_spl_par, degree=_spl_deg,
                        knot_spacing=_spl_knot, verbose=False)
    rv_obj.add_rvGP(rv_list=gp_rvlist,par=gp_pars,kernel=kernels,operation="op",
                        amplitude=amplitude,lengthscale=lengthscale,verbose=verbose)
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    ## Planet parameters
    dump    = _file.readline()
    _adump  = dump.split()
    pl_pars = {}
    pl_pars["rho_star"] = _prior_value(_adump[2])
    par_names = ["RpRs","Impact_para", "T_0", "Period", "Eccentricity","omega", "K"]
    for p in par_names: pl_pars[p] = []
        
    for n in range(1,nplanet+1):        #load parameters for each planet
        _skip_lines(_file,1)          #remove dashes
        for i in range(7):
            dump =_file.readline()
            _adump = dump.split()
            pl_pars[par_names[i]].append(_prior_value(_adump[2]))
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    ## limb darkening
    q1, q2 = [],[]
    for _ in range(len(lc_obj._filnames)):
        dump   = _file.readline()
        _adump = dump.split()
        q1.append(_prior_value(_adump[2]))
        q2.append(_prior_value(_adump[3]))
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    #DDFs
    dump   = _file.readline()
    _adump = dump.split()
    ddfyn,ddf_pri,div_wht  = _adump[0], _prior_value(_adump[1]), _adump[2]
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    #phase curve
    D_occ,A_pc,ph_off = [],[],[]    
    for _ in range(len(lc_obj._filnames)):
        dump   = _file.readline()
        _adump = dump.split()
        D_occ.append(_prior_value(_adump[3]))
    _skip_lines(_file,1)                                      #remove 2 comment lines
    for _ in range(len(lc_obj._filnames)):
        dump   = _file.readline()
        _adump = dump.split()
        A_pc.append(_prior_value(_adump[3]))
    _skip_lines(_file,1)                                      #remove 2 comment lines
    for _ in range(len(lc_obj._filnames)):
        dump   = _file.readline()
        _adump = dump.split()
        ph_off.append(_prior_value(_adump[3]))
    
    _skip_lines(_file,3)                                      #remove 3 comment lines
 
    #contamination factors
    cont_fac = []
    for _ in range(len(lc_obj._filnames)):
        dump   = _file.readline()
        _adump = dump.split()
        cont_fac.append(_prior_value(_adump[1]))
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    lc_obj.planet_parameters(**pl_pars,verbose=verbose)
    lc_obj.limb_darkening(q1,q2,verbose=verbose)
    lc_obj.transit_depth_variation(ddFs=ddfyn,dRpRs=ddf_pri, divwhite=div_wht,verbose=verbose)
    lc_obj.setup_phasecurve(D_occ, A_pc, ph_off, verbose=verbose)
    lc_obj.contamination_factors(cont_ratio=cont_fac, verbose=verbose)
    
    
    # stellar params
    dump    = _file.readline()
    _adump  = dump.split()
    st_rad  = _prior_value(_adump[1])
    dump    = _file.readline()
    _adump  = dump.split()
    st_mass = _prior_value(_adump[1])
    dump    = _file.readline()
    _adump  = dump.split()
    par_in  = _adump[2]
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    #fit setup
    tot_samps = int(_file.readline().split()[1])
    nchains   = int(_file.readline().split()[1])
    nsteps    = int(tot_samps/nchains)
    ncpus     = int(_file.readline().split()[1])
    nburn     = int(_file.readline().split()[1])
    nlive     = int(_file.readline().split()[1])
    dlogz     = float(_file.readline().split()[1])
    sampler   = _file.readline().split()[1]
    mc_move   = _file.readline().split()[1]
    lsq_base  = _file.readline().split()[1]
    lcjitt    = _file.readline().split()[1]
    rvjitt    = _file.readline().split()[1]
    
    _adump    = _file.readline().split()
    baselo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
    basehi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
    lcbaselim = [baselo, basehi]
    
    _adump    = _file.readline().split()
    baselo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
    basehi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
    rvbaselim = [baselo, basehi]
    
    fit_obj = fit_setup(R_st = st_rad, M_st = st_mass, par_input=par_in,
                        apply_LCjitter=lcjitt, apply_RVjitter=rvjitt,
                        leastsq_for_basepar=lsq_base, 
                        LCbasecoeff_lims=lcbaselim, RVbasecoeff_lims=rvbaselim,
                        verbose=verbose)
    
    fit_obj.sampling(sampler=sampler,n_cpus=ncpus, emcee_move=mc_move,
                    n_chains=nchains, n_burn   = 5000, n_steps  = nsteps, 
                    n_live=nlive, dyn_dlogz=dlogz,verbose=verbose )

    _file.close()

    if return_fit:
        from .fit_data import run_fit
        result =   run_fit(lc_obj, rv_obj, fit_obj) 
        return lc_obj,rv_obj,fit_obj,result

    return lc_obj,rv_obj,fit_obj



