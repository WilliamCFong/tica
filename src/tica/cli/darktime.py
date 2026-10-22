import argparse
import os
import re
import sys

import matplotlib.pyplot as plt
import numpy as np


#need reference image for WCS.  not too strigent, should be dark time. 1 image
#need images for reference image.  Must be dark.  only need 20
#need dark time intervals for RMS.  Must be dark, but balanced against as much time as possible


def clean_islands(FFInums, mask_keep, N_ffis_per_island):


    good_idx = np.where(mask_keep)[0]
    if len(good_idx) == 0:
        return mask_keep
    min_idx = good_idx[0]
    max_idx = good_idx[-1]


    island_keep = np.zeros(len(FFInums),dtype=bool)

    for ii in range(len( good_idx )):
        idx = good_idx[ii]

        if idx != min_idx:
            dt1 = FFInums[idx] - FFInums[good_idx[ii - 1 ] ]
            #print(dt1)
            #if next time interval is smaller than 1hr = 18 FFIs, grab
            #these FFIs
            if (dt1 < N_ffis_per_island) & (dt1 > 1):
                #print(idx,dt1,'in dt1 additions')
                m = (FFInums > FFInums[good_idx[ii -1] ]) & ( FFInums < FFInums[idx ])
                island_keep[ m ] = 1


        if idx != max_idx:

            dt2 = FFInums[good_idx[ii + 1 ]] - FFInums[idx ]
            if (dt2 < N_ffis_per_island) & ( dt2 > 1):
                #print(idx,dt2,'in dt2 additions')
                m = (FFInums > FFInums[idx]) & ( FFInums < FFInums[good_idx[ii + 1 ]])
                island_keep[ m ] = 1

    return island_keep + mask_keep



#N_low_modes = 3
#mode_sigma = 5
frac_above_min = 1.10

# A CCD background at or below this fraction of the CCD's 10th percentile is a
# calibration problem, not dark sky: e.g. a bias spoiled by a saturating
# stray-light source, as on camera 1 at FIN 01324272 of orbit 227.
MISCALIBRATED_FRACTION = 0.5


def load_timeseries(infile):
    """(FFInums, names, data, straylight) from a cal_timeseries.txt, sorted by FIN.

    straylight is the STRAYLT1-4 bitmask per frame, or None for files written
    before that column was added.
    """
    with open(infile) as f:
        columns = f.readline().split()
    fname_all = np.genfromtxt(infile,unpack=1,usecols=(0),dtype=str,skip_header=1)
    data_all  = np.genfromtxt(infile,names=True,usecols=tuple(range(1, 21)))
    straylight = None
    if 'straylight' in columns:
        straylight = np.atleast_1d(np.genfromtxt(infile, usecols=(columns.index('straylight'),),
                                                 skip_header=1, dtype=int))
    FFInum_all = np.array([ int(e.split('-')[1]) for e in fname_all  ])
    idx = np.argsort(FFInum_all)
    return (FFInum_all[idx], fname_all[idx], data_all[idx],
            None if straylight is None else straylight[idx])


def bad_calibration(data_all, jj):
    """Frames with a bad calibration of CCD jj+1.

    An overclock (1D bias) correction more than 20 sigma from the median on
    any output, e.g. from saturation by the Earth or Moon, or a background mode
    of 0, which is set if saturation is not yet spiking the overclocks but the
    imaging array is near zero or negative.
    """
    bad = np.zeros(len(data_all), dtype=bool)
    for output_channel in ['A','B','C','D']:
        overclock_correct = data_all['output{}_ccd{}'.format(output_channel, jj+1)]
        deviations = overclock_correct - np.median(overclock_correct)
        scatter = np.median(abs(deviations))/0.67449
        bad |= abs(deviations) > 20*scatter
    return bad | (data_all['mode_ccd{}'.format(jj+1)] == 0)


def choose_reffin(series):
    """One WCS reference FIN for all 16 CCDs; returns (FIN or None, explanation).

    series has (FFInums, data, straylight) for each camera, as from
    load_timeseries. Candidates are the frames of all four cameras with no bad
    calibration on any CCD (bad_calibration, or a background at most
    MISCALIBRATED_FRACTION of that CCD's 10th percentile) and no stray-light
    flag. The candidate whose worst CCD is least above its own 10th-percentile
    background is chosen. If every candidate has a stray-light flag, the flags
    are ignored.
    """
    fins = np.array(sorted(set.intersection(*(set(f.tolist()) for f, _, _ in series))))
    if len(fins) == 0:
        return None, 'the cameras have no frame in common'
    ok = np.ones(len(fins), dtype=bool)
    stray = np.zeros(len(fins), dtype=bool)
    ratios = []
    for fin_all, data, straylight in series:
        pos = np.searchsorted(fin_all, fins)
        if straylight is not None:
            stray |= straylight[pos] != 0
        for jj in range(4):
            mode_all = data['mode_ccd{}'.format(jj+1)]
            positive = mode_all[mode_all > 0]
            dark = np.percentile(positive, 10) if len(positive) else np.inf
            mode = mode_all[pos]
            ok &= ~bad_calibration(data, jj)[pos] & (mode > MISCALIBRATED_FRACTION*dark)
            ratios.append(mode/dark)
    worst = np.max(ratios, axis=0)
    for use, note in ((ok & ~stray, ''),
                      (ok, '; every well-calibrated frame has a stray-light flag, so the flags '
                           'were ignored')):
        if use.any():
            k = np.flatnonzero(use)[np.argmin(worst[use])]
            return int(fins[k]), ('FIN {:08d}, whose worst CCD is at {:.2f}x its 10th-percentile '
                                  'background ({} of {} frames were candidates){}'.format(
                                      fins[k], worst[k], int(use.sum()), len(fins), note))
    return None, 'no frame is well calibrated on all 16 CCDs'


def build_parser():
    description_string = """

    This script reads cal_timeseries.txt files, and identifies periods
    of darktime needed for further processing.  It also identifies bad
    calibrations based on the overclock corrections (for example, due
    to saturated output channels from the earth/moon).

    The outputs are an REFFIN needed for TICA wcs, a list of 20 dark
    frames needed to make the difference imaging reference, and a long
    list for rms images after the difference imaging (for a transient
    search).

    The REFFIN is one frame for all 16 CCDs: the frame whose worst CCD is
    closest to its own dark background, among frames with no bad
    calibration on any CCD and, when cal_timeseries.txt records them, no
    stray-light flag (STRAYLT1-4). reffin.txt lists it for every CCD. With
    --save_reffin, exits 1 if there is no such frame.

    """

    parser = argparse.ArgumentParser(prog='tica-darktime', description = description_string,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode_sigma",type=float,default=8.0,
                        help="Determines threshold for rms_list.  "
                        "rms_list is longest stretch of dark time, "
                        "we use this to build the variability image "
                        "for transient detections. Take "
                        "mode_sigma*min(mode_bins) for rms_list.")

    parser.add_argument("--N_low_modes",type=int,default=3,
                        help="Determines number of low mode_bins "
                        "for ref_list.  ref_list is the 20 darkesst "
                        "frames, for making reference image for difference imaging.")

    parser.add_argument("--N_ffis_per_island",type=int, default=120,
                        help="Due to noise, some points jump above thresholds within"
                        "darktime intervales.  This is the minimum number of points"
                        "to be considered bright time, as apposed to on of these "
                        "spurious islands.")

    parser.add_argument("--use_first_ccd",action='store_true',
                        help="If set, copy cam1_ccd1/ref_list to other CCDs.")

    parser.add_argument("--save_reffin",action='store_true',
                        help="If set, save the WCS reference REFFIN (see above) in reffin.txt, "
                        "to use with tica-wcs-step1.")

    parser.add_argument("--save_reflist",action='store_true',
                        help="If set, save 20 good REFFINs in cam?_ccd?/ref_list, "
                        "suitable for making reference image for DIA.")

    parser.add_argument("--orbit",type=str,default='',
                        help="If set, addes the orbit name to the image title and filename."
                        "If not set, just ignores.")


    parser.add_argument("--show", action='store_true',
                        help="Show the diagnostic plots in a window after saving them.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.save_reffin:
        if os.path.isfile('reffin.txt'):
            os.remove('reffin.txt')

    series = [load_timeseries('cam{}_ccd1/cal_timeseries.txt'.format(ii + 1)) for ii in range(4)]
    global_reffin, why = choose_reffin([(f, d, st) for f, _, d, st in series])
    print('Read {} frames per camera; WCS reference frame: {}'.format(
        '/'.join(str(len(f)) for f, _, _, _ in series), why))
    if args.save_reffin:
        if global_reffin is None:
            print('Error: no WCS reference frame; reffin.txt not written.')
        else:
            #the same frame for every CCD
            with open('reffin.txt','w') as fout:
                for ii in range(4):
                    for jj in range(4):
                        fout.write('cam{}_ccd{} {:08d}\n'.format(ii + 1, jj + 1, global_reffin))

    for ii in range(4):
        infile = 'cam{}_ccd1/cal_timeseries.txt'.format(ii + 1)
        FFInum_all, fname_all, data_all, _ = series[ii]



        F,( axes ) = plt.subplots(4, 2,sharex='all')

        for jj in range(len(axes)):

            ccduse = 'mode_ccd{}'.format(jj+1)

            try:
                axes[jj][1].plot(FFInum_all, data_all['outputA_ccd{}'.format(jj+1)], 'k.')
                axes[jj][1].plot(FFInum_all, data_all['outputB_ccd{}'.format(jj+1)], 'k.')
                axes[jj][1].plot(FFInum_all, data_all['outputC_ccd{}'.format(jj+1)], 'k.')
                axes[jj][1].plot(FFInum_all, data_all['outputD_ccd{}'.format(jj+1)], 'k.')
            except Exception:
                pass



            ########################################################
            #bad_calibration
            ########################################################
            bad_cal_trim = bad_calibration(data_all, jj)

            for output_channel in ['A','B','C','D']:
                overclock_correct = data_all['output{}_ccd{}'.format(output_channel,
                                                                 jj+1)]

                deviations = overclock_correct   - np.median(overclock_correct)
                scatter = np.median(  abs( deviations) )/0.67449

                low = np.ones(len(FFInum_all))*(np.median(overclock_correct)  - 18*scatter)
                high = np.ones(len(FFInum_all))*(np.median(overclock_correct) + 18*scatter)
                axes[jj][1].fill_between(FFInum_all, high, low, facecolor='k',alpha=0.2)

                axes[jj][1].plot(FFInum_all[bad_cal_trim],
                                 data_all['output{}_ccd{}'.format(output_channel,
                                                                  jj+1)][bad_cal_trim], 'r.')

            if len(np.where(bad_cal_trim)[0]) > 0:
                np.savetxt('cam{}_ccd{}/bad_calibration.txt'.format(ii + 1, jj+1),
                           np.c_[FFInum_all[bad_cal_trim] ],
                           fmt='%d')
                data = data_all[~bad_cal_trim]
                FFInum = FFInum_all[~bad_cal_trim]
                fname = fname_all[~bad_cal_trim]
            else:
                data   = data_all
                FFInum = FFInum_all
                fname  = fname_all


            ########################################################
            #rms_list
            ########################################################

            unique_modes = np.unique(data['mode_ccd{}'.format(jj+1)])
            thresh = args.mode_sigma*np.sqrt( unique_modes[0]) + unique_modes[0]

            axes[jj][0].plot(FFInum, data['mode_ccd{}'.format(jj+1)], 'k.')
            axes[jj][0].set_ylabel('CCD {}'.format(jj+1))

            #print(unique_modes)



            m = data[ccduse] < unique_modes[0]*frac_above_min
            m = clean_islands(FFInum, m, args.N_ffis_per_island)
            axes[jj][0].plot(FFInum[m], data[ccduse][m],'c.',
                             label='$<$ {} of lowest bkg'.format(frac_above_min) )
            #make_rms(FFInum[m],ii+1,jj+1,'mask1_rms.fits')

            #m = data['mode_ccd{}'.format(jj+1)] < unique_modes[low_modes_num]
            m = data[ccduse] < thresh
            m = clean_islands(FFInum, m, args.N_ffis_per_island)

            axes[jj][0].plot(FFInum[m], data[ccduse][m],'b.',
                             label=r'$<$ {}$\sigma$ of lowest bkg'.format(args.mode_sigma) )
            lo,hi = axes[jj][0].get_xlim()
            axes[jj][0].plot([lo,hi], [thresh,thresh],'b--')
            axes[jj][0].set_xlim([lo,hi])

            #make_rms(FFInum[m],ii+1,jj+1,'mask2_rms.fits')
            #seems to work well for dark time interval, save for rms_list
            outnames = []
            if len(fname[m]) < 20:
                m = data[ccduse] < unique_modes[0]*frac_above_min
                m = clean_islands(FFInum, m, args.N_ffis_per_island)

            for e in fname[m]:
                out1 = 'conv_{}'.format(e).replace('.fits','_ccd{}.cal.fits'.format(jj+1) )
                out1 = out1.replace('.gz','')
                outnames.append(out1)


            np.savetxt('cam{}_ccd{}/rms_list'.format(ii+1, jj+1),
                       np.c_[outnames],fmt='%s')



            ########################################################
            #REFFIN
            ########################################################
            #one frame for all CCDs (choose_reffin); without one, mark this
            #CCD's darkest frame, near the middle of the lowest bin
            if global_reffin is not None:
                reffin = global_reffin
            else:
                m = data[ccduse] == unique_modes.min()
                idxs = np.where(m)[0]
                reffin = FFInum[idxs[ len(idxs)//2 ]]

            lo,hi = axes[jj][0].get_ylim()
            axes[jj][0].plot([reffin,reffin],
                             [lo,hi],'k--')
            axes[jj][0].set_ylim([lo,hi])

            ########################################################
            #ref_list
            ########################################################
            #pick 20 that are at darkest times
            #have been assuming that spread out over time is good
            #so, lowest few bins, and evenly spread over time
            try:
                m = data[ccduse] <= unique_modes[args.N_low_modes]
                kk = 0
                while len(m[m]) < 25:
                    kk += 1
                    m = data[ccduse] <= unique_modes[args.N_low_modes + kk ]

                m = clean_islands(FFInum, m, args.N_ffis_per_island)
                idxs = np.where(m)[0]
                #trim 10% on boths sides
                trim = int(len(idxs)*0.25)
                idxs = idxs[trim:-trim]

                #this is 20 points evenly spaced across the dark time range
                #idx_ref = idxs[ np.r_[0:len(idxs) -1 :20j].astype(int) ]

                #best is to concentrate them in time, about over 1
                #1 day = 432 FFIs
                #but, if not settle for 20 equal distributed
                idx_mid = len(idxs)//2

                if len(idxs) > 433:
                    idx_ref = idxs[ np.r_[idx_mid - 216 : idx_mid + 216 :20j].astype(int) ]
                elif len(idxs) > 20:
                    #print(idxs)
                    idx_ref = idxs[ np.r_[0:len(idxs)-1:20j].astype(int) ]
                else:
                    idx_ref = idxs



                axes[jj][0].plot(FFInum[idxs],data['mode_ccd{}'.format(jj+1)][idxs],
                                 '.',color='purple',
                                 label='Trimmed times for ref')

                lo,hi = axes[jj][0].get_ylim()
                for idx_r in idx_ref:

                    axes[jj][0].plot([FFInum[idx_r],FFInum[idx_r]],
                                     [lo,hi],'r--')
                axes[jj][0].set_ylim([lo,hi])




                if args.save_reflist:
                    if args.use_first_ccd:
                        if ii == 0 and jj == 0:
                            with open('cam{}_ccd{}/ref_list'.format(ii+1,jj+1),'w') as fout:
                                fstem = fname[0].split('-')[0]
                                for idx_r in idx_ref:
                                    fout.write('{}-{:08d}-{}-crm-ffi_ccd{}.cal.fits\n'.format(
                                        fstem,FFInum[idx_r], ii+1, jj + 1))

                    else:
                        with open('cam{}_ccd{}/ref_list'.format(ii+1,jj+1),'w') as fout:
                            fstem = fname[0].split('-')[0]
                            for idx_r in idx_ref:
                                fout.write('{}-{:08d}-{}-crm-ffi_ccd{}.cal.fits\n'.format(
                                    fstem,FFInum[idx_r], ii+1, jj + 1))
            except Exception as e:
                print('cam{} ccd{}: could not make ref_list: {}'.format(ii + 1, jj + 1, e))


        wrkdir = os.getcwd()
        sector_match = re.search(r'sector(\d+)', wrkdir)
        sector = sector_match.group(1)

        if args.orbit:
            F.suptitle('cam{} sector{} o{}'.format(ii+1, sector, args.orbit), )
        else:
            F.suptitle('cam{} sector{}'.format(ii+1, sector), )

        axes[0][0].set_title('Image mode (background)')

        axes[00][0].legend(fontsize=8)

        axes[0][1].set_title('1D Bias correction')

        F.set_size_inches(12,8)
        F.subplots_adjust(hspace=0)


        if args.orbit:
            F.savefig(os.path.join( os.path.dirname(infile), 'cal_timeseries_{}.png' .format(args.orbit) ) )
        else:
            F.savefig(os.path.join( os.path.dirname(infile), 'cal_timeseries.png') )

    if args.show:
        plt.show()
    return 1 if args.save_reffin and global_reffin is None else 0


if __name__ == "__main__":
    sys.exit(main())
