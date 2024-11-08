from ._classes import load_lightcurves, load_rvs, fit_setup,_print_output
from .utils import ecc_om_par
import numpy as np 



def fit_configfile(config_file = "input_config.dat", out_folder = "output", 
                   init_decorr=False, rerun_result=True, resume_sampling=False, verbose=False):
    """
        Run CONAN fit from configuration file. 
        This loads the config file and creates the required objects (lc_obj, rv_obj, fit_obj) to perform the fit.
        
        Parameters:
        -----------
        config_file: filepath;
            path to configuration file.
        out_folder: filepath;
            path to folder where output files will be saved.
        init_decorr: bool;
            whether to run least-squares fit to determine start values of the decorrelation parameters. 
            Default is False
        rerun_result: bool;
            whether to rerun using with already exisiting result inorder to remake plots/files. Default is True
        resume_sampling: bool;
            resume sampling from last saved position 
        verbose: bool;
            show print statements
    """
    from .fit_data import run_fit

    lc_obj, rv_obj, fit_obj = load_configfile(config_file, init_decorr=init_decorr, verbose=verbose)
    result = run_fit(lc_obj, rv_obj, fit_obj,out_folder=out_folder,
                        rerun_result=rerun_result,resume_sampling=resume_sampling,verbose=verbose)
    return result


def _skip_lines(file, n):
    """ takes an open file object and skips the reading of lines by n lines """
    for i in range(n):
        dump = file.readline()

def _prior_value(str_prior): 
    "convert string prior into float/tuple"
    str_prior = str_prior[str_prior.find("(")+1:str_prior.find(")")].split(",")
    tuple_prior = [float(v) for v in str_prior]
    tuple_prior = [(int(v) if v.is_integer() else float(v)) for v in tuple_prior]
    len_tup = len(tuple_prior)
    val = tuple_prior[0] if len_tup==1 else tuple(tuple_prior)
    return val



def create_configfile(lc_obj=None, rv_obj=None, fit_obj=None, filename="input_config.dat"): 
    """
        create configuration file that of lc_obj, rv_obj, amd fit_obj setup.
        
        Parameters:
        -----------
        lc_obj : object,None;
            Instance of CONAN.load_lightcurve() object and its attributes.

        rv_obj : object, None;
            Instance of CONAN.load_rvs() object and its attributes.
        
        fit_obj : object;
            Instance of CONAN.fit_setup() object and its attributes.

        filename : str;
            name of the configuration file to be saved.
    """
    if lc_obj is None:
        lc_obj = load_lightcurves()
    if rv_obj is None:
        rv_obj = load_rvs()
    if fit_obj is None:
        fit_obj = fit_setup()
    f = open(filename,"w")
    f.write("# ========================================== CONAN configuration file ============================================= \n")
    f.write("#             *********** KEYS *****************************************************************************************\n")
    f.write("#             PRIORS: *Fixed - F(val), *Normal - N(mu,std), *Uniform - U(min,start,max), *LogUniform - LU(min,start,max)\n")
    f.write("#             s_samp: supersampling - x{exp_time(mins)}\n")
    f.write("#             clip:   clip outliers - W{window_width}C{clip_sigma}\n")
    f.write("#             scl_col: scale data columns – ['med_sub','rs0to1','rs-1to1','None']\n")
    f.write("#             spline_config: spline - c{column_no}:d{degree}K{knot_spacing}\n")
    f.write("#             ***********************************************************************************************************\n")
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    f.write(f"\tLC_filepath: {lc_obj._fpath}\n")
    f.write(f"\tRV_filepath: {rv_obj._fpath}\n")
    f.write(f"\tn_planet: {lc_obj._nplanet}\n")
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    f.write(f"\t{'LC_auto_decorr:':15s} False   | delta_BIC: -5  # automatically determine baseline function for LCs with delta_BIC=-5\n")
    f.write(f"\t{'exclude_cols:':15s} []                         # list of column numbers (e.g. [3,4]) to exclude from decorrelation.\n")
    f.write(f"\t{'enforce_pars:':15s} []                         # list of decorr params (e.g. [B3, A5]) to enforce in decorrelation\n")
    _print_output(lc_obj,"lc_baseline",file=f)
    _print_output(lc_obj,"gp",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    f.write(f"\t{'RV_auto_decorr:':15s} False   | delta_BIC: -5  # automatically determine baseline function for the RVs\n")
    f.write(f"\t{'exclude_cols:':15s} []                         # list of column numbers (e.g. [3,4]) to exclude from decorrelation.\n")
    f.write(f"\t{'enforce_pars:':15s} []                         # list of decorr params (e.g. [B3, A5]) to enforce in decorrelation\n")
    _print_output(rv_obj,"rv_baseline",file=f)
    _print_output(rv_obj,"rv_gp",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(lc_obj,"planet_parameters",file=f)
    _print_output(lc_obj,"limb_darkening",file=f)
    _print_output(lc_obj,"depth_variation",file=f)
    _print_output(lc_obj,"timing_variation",file=f)
    _print_output(lc_obj,"phasecurve",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(lc_obj,"contamination",file=f)
    _print_output(fit_obj,"stellar_pars",file=f)
    f.write("# -----------------------------------------------------------------------------------------------------------------------\n")
    _print_output(fit_obj, "fit",file=f)
    f.close()
    print(f"configuration file saved as {filename}")


def load_configfile(configfile="input_config.dat", return_fit=False, init_decorr=False, verbose=False):
    """
        configure conan from specified configfile.
        
        Parameters:
        -----------
        configfile: filepath;
            path to configuration file.

        return_fit: bool;
            whether to immediately perform the fit from this function call.
            if True, the result object from the fit is also returned

        init_decorr: bool;
            whether to run least-squares fit to determine start values of the decorrelation parameters. 
            Default is False

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

    _file = open(configfile,"r")
    _skip_lines(_file,9)                       #remove first 2 comment lines
    fpath    = _file.readline().rstrip().split()[1]           # the path where the files are
    rv_fpath = _file.readline().rstrip().split()[1]           # the path where the files are
    nplanet  = int(_file.readline().rstrip().split()[1])      # the path where the files are
    _skip_lines(_file,1)                                      #remove 3 comment lines

    #### auto decorrelation
    dump   = _file.readline().rstrip()
    _adump = dump.split()
    assert _adump[1] in ["True","False"], f"LC_auto_decorr: must be 'True' or 'False' but {_adump[1]} given"
    use_decorr = True if _adump[1] == "True" else False
    del_BIC = float(_adump[4]) if len(_adump) > 4 else -5
    dump = _file.readline().rstrip().split()[1]
    assert dump[0] == "[" and dump[-1] == "]", f"exclude_cols: must be a list of column numbers (e.g. [3,4]) but {dump} given"
    #convert dump to list of ints
    exclude_cols = [int(i) for i in dump[1:-1].split(",")] if dump[1]!= "]" else []
    dump = _file.readline().rstrip().split()[1]
    assert dump[0] == "[" and dump[-1] == "]", f"enforce_pars: must be a list of  pars (e.g. [B3,A5]) but {dump} given"
    #convert dump to list of strings
    enforce_pars = [i for i in dump[1:-1].split(",")] if dump[1]!= "]" else []
    _skip_lines(_file,2)                                      #remove 1 comment lines

    # ========== Lightcurve input ====================
    _names=[]                    # array where the LC filenames are supposed to go
    _filters=[]                  # array where the filter names are supposed to go
    _wl=[]
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
        _wl.append(float(_adump[2]))    # append the second field to the filters array
        
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
        
        #scale columns
        _sclcol.append(_adump[5])

        strbase=_adump[7:13]
        strbase.append(_adump[13].split("|")[0])        # string array of the baseline function coeffs
        grbase = 0
        strbase.extend([_adump[14],grbase])
        _grbases.append(grbase)
        base = [int(i) for i in strbase]
        _bases.append(base)
        
        group = int(_adump[15])
        _groups.append(group)
        _useGPphot.append(_adump[16])
        
        #LC spline
        if _adump[17] != "None": 
            _spl_lclist.append(_adump[0])
            if "|" not in _adump[17]:   #1D spline
                k1 = _adump[17].split("k")[-1]
                _spl_knot.append(float(k1) if k1 != "r" else k1)
                _spl_deg.append(int(_adump[17].split("k")[0].split("d")[-1]))
                _spl_par.append("col" + _adump[17].split("d")[0][1])
            else: #2D spline
                sp = _adump[17].split("|")  #split the diff spline configs
                k1,k2 = sp[0].split("k")[-1], sp[1].split("k")[-1]
                _spl_knot.append( (float(k1) if k1!="r" else k1, float(k2) if k2!="r" else k2) )
                _spl_deg.append( (int(sp[0].split("k")[0].split("d")[-1]),int(sp[1].split("k")[0].split("d")[-1])) )
                _spl_par.append( ("col"+sp[0].split("d")[0][1],"col"+sp[1].split("d")[0][1]) ) 
        #move to next LC
        dump =_file.readline() 
    

    nphot = len(_names)
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
            gp_pars[-1]     = (gp_pars[-1],_adump[7])
            kernels[-1]     = (kernels[-1],_adump[8])
            amplitude[-1]   = (amplitude[-1],_prior_value(_adump[9]))
            lengthscale[-1] = (lengthscale[-1],_prior_value(_adump[10]))

        #move to next LC
        dump =_file.readline()
    # _skip_lines(_file,1)  
    
    
    # instantiate light curve object
    lc_obj = load_lightcurves(_names, fpath, _filters, _wl, nplanet)
    lc_obj.lc_baseline(*np.array(_bases).T, grp_id=None, gp=_useGPphot,verbose=False )
    lc_obj.clip_outliers(lc_list=_clip_lclist , clip=_clip, width=_clip_width,show_plot=False,verbose=False )
    lc_obj.rescale_data_columns(method=_sclcol,verbose=False)
    lc_obj.supersample(lc_list=_ss_lclist, exp_time=_ss_exp, verbose=False)
    lc_obj.add_spline(lc_list=_spl_lclist ,par=_spl_par , degree=_spl_deg,
                        knot_spacing=_spl_knot , verbose=False)
    if verbose: lc_obj.print("lc_baseline")
    if gp_lclist !=[]: gp_lclist = gp_lclist[0] if gp_lclist[0]=='same' else gp_lclist
    lc_obj.add_GP(lc_list=gp_lclist,par=gp_pars,kernel=kernels,operation=op,
                    amplitude=amplitude,lengthscale=lengthscale,verbose=verbose)
    
    ## RV ==========================================================
    #### auto decorrelation
    dump = _file.readline().rstrip()
    _adump = dump.split()
    assert _adump[1] in ["True","False"], f"RV_auto_decorr: must be 'True' or 'False' but {_adump[1]} given"
    use_decorrRV = True if _adump[1] == "True" else False
    rvdel_BIC = float(_adump[4]) if len(_adump) > 4 else -5
    dump = _file.readline().rstrip().split()[1]
    assert dump[0] == "[" and dump[-1] == "]", f"RV exclude_cols: must be a list of column numbers (e.g. [3,4]) but {dump} given"
    #convert dump to list of ints
    exclude_colsRV = [int(i) for i in dump[1:-1].split(",")] if dump[1]!= "]" else []
    dump = _file.readline().rstrip().split()[1]
    assert dump[0] == "[" and dump[-1] == "]", f"RV enforce_pars: must be a list of  pars (e.g. [B3,A5]) but {dump} given"
    #convert dump to list of strings
    enforce_parsRV = [i for i in dump[1:-1].split(",")] if dump[1]!= "]" else []
    _skip_lines(_file,2)                                      #remove 1 comment lines

    RVnames, RVbases, gammas = [],[],[]
    _RVsclcol, usegpRV,strbase = [],[],[]
    _spl_rvlist,_spl_deg,_spl_par, _spl_knot=[],[],[],[]
    RVunit = "km/s"
    
    dump =_file.readline()
    while dump[0] != '#':                   # if it is not starting with # then
        _adump = dump.split()               # split it
        RVnames.append(_adump[0])
        RVunit = _adump[1]
        _RVsclcol.append(_adump[2])
        strbase=_adump[4:7]                  # string array of the baseline function coeffs
        strbase.append(_adump[7].split("|")[0])
        strbase.append(_adump[8])
        base = [int(i) for i in strbase]
        RVbases.append(base)
        usegpRV.append(_adump[9])
        
        #RV spline
        if _adump[10] != "None":
            _spl_rvlist.append(_adump[0])
            if "|" not in _adump[10]:
                _spl_knot.append(float(_adump[10].split("k")[-1]))
                _spl_deg.append(int(_adump[10].split("k")[0].split("d")[-1]))
                _spl_par.append("col" + _adump[10].split("d")[0][1])
            else:
                sp = _adump[10].split("|") #split the diff spline configs
                _spl_knot.append( (float(sp[0].split("k")[-1]),float(sp[1].split("k")[-1])) )
                _spl_deg.append( (int(sp[0].split("k")[0].split("d")[-1]),int(sp[1].split("k")[0].split("d")[-1])) )
                _spl_par.append( ("col"+sp[0].split("d")[0][1],"col"+sp[1].split("d")[0][1]) )
        
        gammas.append(_prior_value(_adump[12]))
        #move to next RV
        dump =_file.readline()
    

    nRV = len(RVnames)
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
            gp_pars[-1]     = (gp_pars[-1],_adump[7])
            kernels[-1]     = (kernels[-1],_adump[8])
            amplitude[-1]   = (amplitude[-1],_prior_value(_adump[9]))
            lengthscale[-1] = (lengthscale[-1],_prior_value(_adump[10]))

        #move to next RV
        dump =_file.readline()
        
        
    rv_obj = load_rvs(RVnames,rv_fpath, nplanet=nplanet,rv_unit=RVunit,lc_obj=lc_obj)
    rv_obj.rv_baseline(*np.array(RVbases).T, gamma=gammas,gp=usegpRV,verbose=False) 
    rv_obj.rescale_data_columns(method=_RVsclcol,verbose=False)
    rv_obj.add_spline(rv_list=_spl_rvlist ,par=_spl_par, degree=_spl_deg,
                        knot_spacing=_spl_knot, verbose=False)
    if verbose: rv_obj.print("rv_baseline")
    if gp_rvlist !=[]: gp_rvlist = gp_rvlist[0] if gp_rvlist[0]=='same' else gp_rvlist
    rv_obj.add_rvGP(rv_list=gp_rvlist,par=gp_pars,kernel=kernels,operation=op,
                    amplitude=amplitude,lengthscale=lengthscale,verbose=verbose)
    
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    ## Planet parameters
    dump    = _file.readline()
    _adump  = dump.split()
    pl_pars = {}
    rho_dur = _adump[0]
    #select string in rho_dur with []
    rho_dur = rho_dur[rho_dur.find("[")+1:rho_dur.find("]")]
    pl_pars[rho_dur] = _prior_value(_adump[2])
    par_names = ["RpRs","Impact_para", "T_0", "Period", "Eccentricity","omega", "K"]
    for p in par_names: pl_pars[p] = []
    sesinw, secosw = [],[]
        
    for n in range(1,nplanet+1):        #load parameters for each planet
        _skip_lines(_file,1)          #remove dashes
        for i in range(7):
            dump =_file.readline()
            _adump = dump.split()
            pl_pars[par_names[i]].append(_prior_value(_adump[2]))
        sesinw_, secosw_ = ecc_om_par(pl_pars["Eccentricity"][-1],pl_pars["omega"][-1],
                                conv_2_obj=True,return_tuple=True)
        sesinw.append(sesinw_)
        secosw.append(secosw_)
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    ## limb darkening
    q1, q2 = [],[]
    dump   = _file.readline()
    while dump[0] != "#":
        _adump = dump.split()
        q1.append(_prior_value(_adump[2]))
        q2.append(_prior_value(_adump[3]))
        dump = _file.readline()
    assert len(q1) == len(lc_obj._filnames), f"number of q1 values must be equal to number of unique filters({len(lc_obj._filnames)}) but len(q1)={len(q1)}"
    _skip_lines(_file,1)                                      #remove 2 comment lines

    #DDFs
    dump   = _file.readline()
    _adump = dump.split()
    ddfyn,ddf_pri,div_wht  = _adump[0], _prior_value(_adump[1]), _adump[2]
    _skip_lines(_file,2)                                      #remove 2 comment lines
    
    #TTVS
    dump =_file.readline()
    _adump = dump.split()
    ttvs, dt, base = _adump[0], _prior_value(_adump[1]), float(_adump[2]) 
    _skip_lines(_file,2)                                      #remove 2 comment lines

    #phase curve
    D_occ,A_atm,ph_off,A_ev,A_db = [],[],[],[],[]    
    dump   = _file.readline()
    while dump[0] != "#":
        _adump = dump.split()
        D_occ.append(_prior_value(_adump[1]))
        A_atm.append(_prior_value(_adump[2]))
        ph_off.append(_prior_value(_adump[3]))
        A_ev.append(_prior_value(_adump[4]))
        A_db.append(_prior_value(_adump[5]))
        dump = _file.readline()
    assert len(D_occ) == len(lc_obj._filnames), f"number of D_occ values must be equal to number of unique filters({len(lc_obj._filnames)}) but len(D_occ)={len(D_occ)}"
    _skip_lines(_file,2)                                      #remove 3 comment lines

    #contamination factors
    cont_fac = []
    dump   = _file.readline()
    while dump[0] != "#":
        _adump = dump.split()
        cont_fac.append(_prior_value(_adump[1]))
        dump = _file.readline()
    assert len(cont_fac) == len(lc_obj._filnames), f"number of contamination factors must be equal to number of unique filters({len(lc_obj._filnames)}) but len(cont_fac)={len(cont_fac)}"
    _skip_lines(_file,1)                                      #remove 2 comment lines
    
    lc_obj.planet_parameters(**pl_pars,verbose=verbose)
    lc_obj.limb_darkening(q1,q2,verbose=verbose)
    lc_obj.transit_depth_variation(ddFs=ddfyn,dRpRs=ddf_pri, divwhite=div_wht,verbose=verbose)
    lc_obj.transit_timing_variation(ttvs=ttvs, dt=dt, baseline_amount=base,verbose=verbose)
    lc_obj.setup_phasecurve(D_occ, A_atm, ph_off, A_ev, A_db, verbose=verbose)
    lc_obj.contamination_factors(cont_ratio=cont_fac, verbose=verbose)

    if nphot > 0:
        if use_decorr or init_decorr:
            if init_decorr and verbose: print("\ngetting start values for LC decorrelation parameters ...")
            lc_obj.get_decorr(**pl_pars,q1=q1,q2=q2,
                                D_occ=D_occ[0] if len(D_occ)>0 else 0, 
                                A_atm=A_atm[0] if len(A_atm)>0 else 0, 
                                ph_off=ph_off[0] if len(ph_off)>0 else 0, 
                                A_ev=A_ev[0] if len(A_ev)>0 else 0, 
                                A_db=A_db[0] if len(A_db)>0 else 0, plot_model=False,
                                setup_baseline=use_decorr,exclude_cols=exclude_cols,delta_BIC=del_BIC,
                                enforce_pars=enforce_pars, verbose=verbose if use_decorr else False)
            if init_decorr:  #if not use_decorr, compare the  get_decorr pars to the user-defined ones and only use start values for user-defined ones
                rel_cols = [b[:6] for b in lc_obj._bases]
                _ = [b.insert(1,0) for b in rel_cols for _ in range(2)] #insert 0 to replace cols 1 and 2
                for j in range(lc_obj._nphot):
                    for i,v in enumerate(rel_cols[j]):
                        if i in [1,2]: continue
                        if v == 0: lc_obj._bases_init[j][f"A{i}"] = lc_obj._bases_init[j][f"B{i}"] = 0
                        if v >= 1: lc_obj._bases_init[j][f"A{i}"] = lc_obj._bases_init[j][f"A{i}"]
                        if v == 2: lc_obj._bases_init[j][f"B{i}"] = lc_obj._bases_init[j][f"B{i}"]

    if nRV > 0:
        if use_decorrRV or init_decorr:
            if init_decorr and verbose: print("\ngetting start values for RV decorrelation parameters ...\n")
            rv_obj.get_decorr(T_0=pl_pars["T_0"], Period=pl_pars["Period"], K=pl_pars["K"],
                                sesinw=sesinw,secosw=secosw,
                                gamma=gammas[0] if len(gammas)>0 else 0, setup_baseline=use_decorrRV,
                                exclude_cols=exclude_colsRV, enforce_pars=enforce_parsRV, delta_BIC=rvdel_BIC,
                                plot_model=False,verbose=verbose if use_decorrRV else False)
            if init_decorr:  #if not use_decorr, compare the  get_decorr pars to the user-defined ones and only use start values for user-defined ones
                rel_cols = [b[:6] for b in rv_obj._RVbases]
                _ = [b.insert(1,0) for b in rel_cols for _ in range(2)] #insert 0 to replace cols 1 and 2
                for j in range(rv_obj._nRV):
                    for i,v in enumerate(rel_cols[j]):
                        if i in [1,2]: continue
                        if v == 0: rv_obj._RVbases_init[j][f"A{i}"] = rv_obj._RVbases_init[j][f"B{i}"] = 0
                        if v >= 1: rv_obj._RVbases_init[j][f"A{i}"] = rv_obj._RVbases_init[j][f"A{i}"]
                        if v == 2: rv_obj._RVbases_init[j][f"B{i}"] = rv_obj._RVbases_init[j][f"B{i}"]
                
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
    nsteps    = int(_file.readline().split()[1])
    nchains   = int(_file.readline().split()[1])
    ncpus     = int(_file.readline().split()[1])
    nburn     = int(_file.readline().split()[1])
    nlive     = int(_file.readline().split()[1])
    force_nl  = _file.readline().split()[1]
    force_nl  = True if force_nl == "True" else False
    dlogz     = float(_file.readline().split()[1])
    sampler   = _file.readline().split()[1]
    mc_move   = _file.readline().split()[1]
    dyn_samp  = _file.readline().split()[1]
    lsq_base  = _file.readline().split()[1]
    lcjitt    = _file.readline().split()[1]
    rvjitt    = _file.readline().split()[1]
    #lcjittlims
    _adump    = _file.readline().split()
    if "auto" in _adump[1]:
        lcjittlim = "auto"
    else:
        jittlo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
        jitthi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
        lcjittlim = [jittlo, jitthi]
    #rvjittlims
    _adump    = _file.readline().split()
    if "auto" in _adump[1]:
        rvjittlim = "auto"
    else:
        jittlo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
        jitthi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
        rvjittlim = [jittlo, jitthi]
    
    #LCbasecoeff_lims
    _adump    = _file.readline().split()
    if "auto" in _adump[1]:
        lcbaselim = "auto"
    else:
        baselo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
        basehi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
        lcbaselim = [baselo, basehi]
    #RVbasecoeff_lims
    _adump    = _file.readline().split()
    if "auto" in _adump[1]:
        rvbaselim = "auto"
    else:
        baselo    = float(_adump[1][_adump[1].find("[")+1:_adump[1].find(",")])
        basehi    = float(_adump[2][_adump[2].find("[")+1:_adump[2].find(",")])
        rvbaselim = [baselo, basehi]


    fit_obj = fit_setup(R_st = st_rad, M_st = st_mass, par_input=par_in,
                        apply_LCjitter=lcjitt, apply_RVjitter=rvjitt,
                        leastsq_for_basepar=lsq_base, 
                        LCbasecoeff_lims=lcbaselim, RVbasecoeff_lims=rvbaselim,
                        LCjitter_loglims=lcjittlim, RVjitter_lims=rvjittlim, 
                        verbose=verbose)
    
    fit_obj.sampling(sampler=sampler,n_cpus=ncpus, emcee_move=mc_move,
                    n_chains=nchains, n_burn   = nburn, n_steps  = nsteps, 
                    n_live=nlive, force_nlive=force_nl, nested_sampling=dyn_samp,
                    dyn_dlogz=dlogz,verbose=verbose )

    _file.close()

    if return_fit:
        from .fit_data import run_fit
        result = run_fit(lc_obj, rv_obj, fit_obj) 
        return lc_obj,rv_obj,fit_obj,result

    return lc_obj,rv_obj,fit_obj



