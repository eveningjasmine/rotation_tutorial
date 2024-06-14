import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy.optimize import minimize

#from cpm_utils import summary_plot

# self.file_name = fits_file.split("/")[-1]  # Should I really keep this here?

class CPM(object):
    """
    """
    def __init__(self, fits_file, remove_bad="True"):
        self.file_path = fits_file
        self.file_name = fits_file
        with fits.open(fits_file, mode="readonly") as hdulist:
            self.time = hdulist[1].data["TIME"]
            self.im_fluxes = hdulist[1].data["FLUX"]  # Shape is (Number of Images, 64, 64)
            self.im_errors = hdulist[1].data["FLUX_ERR"]  # Shape is (Number of Images, 64, 64)
            self.quality = hdulist[1].data["QUALITY"]
            try:
                self.wcs_info = WCS(hdulist[2].header)
            except:
                print("WCS Info could not be retrieved")
        
        self.dump_times = self.time[self.quality > 0]
        # If remove_bad is set to True, we'll remove the values with a nonzero entry in the quality array
        if remove_bad == True:
            good = (self.quality == 0)  # The zero value entries for the quality array are the "good" values
#            print("Removing {} bad values by using the TESS provided \"QUALITY\" array".format(np.sum(~good)))
            # self.dump_times = self.time[self.quality > 0]
            self.time = self.time[good]
            self.im_fluxes = self.im_fluxes[good]
            self.im_errors = self.im_errors[good]

        # We're going to precompute the pixel lightcurve medians since it's used to set the predictor pixels
        # but never has to be recomputed

        # self.pixel_medians = np.median(self.im_fluxes, axis=0)
        self.pixel_medians = np.nanmedian(self.im_fluxes, axis=0)

        self.flattened_pixel_medians = self.pixel_medians.reshape(self.im_fluxes[0].shape[0]**2)

        self.rescaled_im_fluxes = (self.im_fluxes/self.pixel_medians) - 1
        self.flattened_rescaled_im_fluxes = self.rescaled_im_fluxes.reshape(self.time.shape[0], self.rescaled_im_fluxes[0].shape[0]**2)

        # self.time = None
        # self.im_fluxes = None
        # self.im_errors = None
        # self.rescaled_im_fluxes = None

        # self._set_current_data(self.orig_time, self.orig_im_fluxes, self.orig_im_errors)
            
        self.target_row = None
        self.target_col = None
        self.target_fluxes = None
        self.target_errors = None
        self.target_median = None
        self.rescaled_target_fluxes = None
        self.rescaled_target_errors = None
        self.target_pixel_mask = None
        
        self.exclusion = None
        self.excluded_pixels_mask = None
        
        # We'll precompute the rescaled values for the fluxes (F* = F/M - 1)
        # self.rescaled_im_fluxes = (self.im_fluxes/self.pixel_medians) - 1
        
        self.method_predictor_pixels = None
        self.num_predictor_pixels = None
        self.predictor_pixels_locations = None
        self.predictor_pixels_mask = None
        self.predictor_pixels_fluxes = None
        self.rescaled_predictor_pixels_fluxes = None
        
        self.rescale = None
        self.polynomials = None
        self.fit = None
        self.cpm_regularization = None
        self.lsq_params = None
        self.cpm_params = None
        self.poly_params = None
        self.orig_m = None
        self.m = None

        self.const_prediction = None
        self.cpm_prediction = None
        self.poly_prediction = None
        self.prediction = None
        self.im_predicted_fluxes = None
        self.im_diff = None
        
        self.is_target_set = False
        self.is_exclusion_set = False
        self.are_predictors_set = False
        self.trained = False
        self.over_entire_image = False

        self.valid = None
        # self.sigma_clipped_time = None
        # self.sigma_clipped_fluxes = None
        # self.sigma_clipped_errors = None

        # self.current_time = None
        # self.current_im_fluxes = None
        # self.current_im_errors = None
        # self.current_scaled_centered_time = None

        # Calculate the vandermode matrix to add polynomial components to model
        # self.current_scaled_centered_time = ((self.current_time - (self.current_time.max() + self.current_time.min())/2) 
        #                             / (self.current_time.max() - self.current_time.min()))
        self.centered_time = None
        self.scaled_centered_time = None
        self.time_interval = None
        # self.v_matrix = np.vander(self.scaled_centered_time, N=4, increasing=True)
        self.poly_terms = None
        self.v_matrix = None
        self.poly_reg = None
        # self.poly_reg_arr = None

    # def _set_current_data(self, current_time, current_im_fluxes, current_im_errors):
    #     self.time = current_time
    #     self.im_fluxes = current_im_fluxes
    #     self.im_errors = current_im_errors
    #     self.rescaled_im_fluxes = (self.im_fluxes/self.pixel_medians) - 1

    def set_poly_model(self, time_interval, poly_terms, poly_reg):
        """Set the polynomial model parameters
        
        """
        self.time_interval = time_interval
        self.centered_time = ((self.time - (self.time.max() + self.time.min())/2)
                                     / (self.time.max() - self.time.min()))
        self.scaled_centered_time = time_interval*self.centered_time
        self.poly_terms = poly_terms
        self.v_matrix = np.vander(self.scaled_centered_time, N=poly_terms, increasing=True)
        self.poly_reg = poly_reg
        # self.poly_reg_arr = np.repeat(self.poly_reg, self.poly_terms)
        
    def set_target(self, target_row, target_col):
        self.target_row = target_row
        self.target_col = target_col
        self.target_fluxes = self.im_fluxes[:, target_row, target_col]  # target pixel lightcurve
        self.target_errors = self.im_errors[:, target_row, target_col]  # target pixel errors
        self.target_median = np.median(self.target_fluxes)
        # print("Target Median is: {}".format(self.target_median))
        self.rescaled_target_fluxes = self.rescaled_im_fluxes[:, target_row, target_col]
        self.rescaled_target_errors = self.target_errors / self.target_median
        
        target_pixel = np.zeros(self.im_fluxes[0].shape)
        target_pixel[target_row, target_col] = 1
        self.target_pixel_mask = np.ma.masked_where(target_pixel == 0, target_pixel)  # mask to see target
        
        self.is_target_set = True
        
    def set_exclusion(self, exclusion, method="closest"):
        if self.is_target_set == False:
            print("Please set the target pixel to predict using the set_target() method.")
            return
        
        r = self.target_row  # just to reduce verbosity for this function
        c = self.target_col
        self.exclusion = exclusion
        exc = exclusion
        im_side_length = self.im_fluxes.shape[1]  # for convenience
        
        excluded_pixels = np.zeros(self.im_fluxes[0].shape)
        if method == "cross":
            excluded_pixels[max(0,r-exc) : min(r+exc+1, im_side_length), :] = 1
            excluded_pixels[:, max(0,c-exc) : min(c+exc+1, im_side_length)] = 1
            
        if method == "row_exclude":
            excluded_pixels[max(0,r-exc) : min(r+exc+1, im_side_length), :] = 1
        
        if method == "col_exclude":
            excluded_pixels[:, max(0,c-exc) : min(c+exc+1, im_side_length)] = 1
        
        if method == "closest":
            excluded_pixels[max(0,r-exc) : min(r+exc+1, im_side_length), 
                            max(0,c-exc) : min(c+exc+1, im_side_length)] = 1
        
        self.excluded_pixels_mask = np.ma.masked_where(excluded_pixels == 0, excluded_pixels)  # excluded pixel is "valid" and therefore False
        self.is_exclusion_set = True
    
    def set_predictor_pixels(self, num_predictor_pixels, method="similar_brightness", seed=None):
        if seed != None:
            np.random.seed(seed=seed)
        
        if (self.is_target_set == False) or (self.is_exclusion_set == False):
            print("Please set the target pixel and exclusion.")
            return 
            
        self.method_predictor_pixels = method
        self.num_predictor_pixels = num_predictor_pixels
        im_side_length = self.im_fluxes.shape[1]  # for convenience (I need column size to make this work)
        
        # I'm going to do this in 1D by assinging individual pixels a single index instead of two.
        coordinate_idx = np.arange(im_side_length**2)
        possible_idx = coordinate_idx[self.excluded_pixels_mask.mask.ravel()]
        
        if method == "random":
            chosen_idx = np.random.choice(possible_idx, size=num_predictor_pixels, replace=False)
        
        if method == "similar_brightness":
            possible_pixel_medians = self.flattened_pixel_medians[self.excluded_pixels_mask.mask.ravel()]
            diff = (np.abs(possible_pixel_medians - self.target_median))
            chosen_idx = possible_idx[np.argsort(diff)[0:self.num_predictor_pixels]]

        if method == "dot_product":
            possible_rescaled_im_fluxes = self.flattened_rescaled_im_fluxes[:,self.excluded_pixels_mask.mask.ravel()]
            # print(possible_rescaled_im_fluxes.shape)
            # norm_target = np.linalg.norm(self.rescaled_target_fluxes)
            dot_products = (np.dot(possible_rescaled_im_fluxes.T, self.rescaled_target_fluxes) 
                            / (np.linalg.norm(possible_rescaled_im_fluxes.T, axis=1)*np.linalg.norm(self.rescaled_target_fluxes)))
            print(dot_products)
            chosen_idx = possible_idx[np.argsort(dot_products)[::-1][0:self.num_predictor_pixels]]
            print(chosen_idx)
            
        self.predictor_pixels_locations = np.array([[idx // im_side_length, idx % im_side_length] 
                                                   for idx in chosen_idx])
        loc = self.predictor_pixels_locations.T
        predictor_pixels = np.zeros((self.im_fluxes[0].shape))
        predictor_pixels[loc[0], loc[1]] = 1
        
        self.predictor_pixels_fluxes = self.im_fluxes[:, loc[0], loc[1]]  # shape is (1282, num_predictors)
        self.rescaled_predictor_pixels_fluxes = self.rescaled_im_fluxes[:, loc[0], loc[1]]
        self.predictor_pixels_mask = np.ma.masked_where(predictor_pixels == 0, predictor_pixels)
        
        self.are_predictors_set = True

    def set_target_exclusion_predictors(self, target_row, target_col, exclusion=10, exclusion_method="closest",
                                       num_predictor_pixels=256, predictor_method="similar_brightness", seed=None):
        """Convenience function that simply calls the set_target, set_exclusion, set_predictor_pixels functions sequentially"""
        self.set_target(target_row, target_col)
        self.set_exclusion(exclusion, method=exclusion_method)
        self.set_predictor_pixels(num_predictor_pixels, method=predictor_method, seed=seed)
        
    def train(self, reg):
        if ((self.is_target_set  == False) or (self.is_exclusion_set == False)
           or self.are_predictors_set == False):
            print("You missed a step.")
        
        def objective(coeff, reg):
            model = np.dot(coeff, self.predictor_pixels_fluxes.T)
            chi2 = ((self.target_fluxes - model)/(self.target_errors))**2
            return np.sum(chi2) + reg*np.sum(coeff**2)
            
        init_coeff = np.zeros(self.num_predictor_pixels)
        self.fit = minimize(objective, init_coeff, args=(reg), tol=0.5)
        self.prediction = np.dot(self.fit.x, self.predictor_pixels_fluxes.T)
        print(self.fit.success)
        print(self.fit.message)
        
        self.trained = True
        
    def lsq(self, cpm_reg, rescale=True, polynomials=False, updated_y=None, updated_m=None):
        """Perform linear least squares with L2-regularization to find the coefficients for the model

        .. note:: Although we have the flux errors, we chose not to include them (i.e. not do weighted least squares)
                    for computational efficiency for now. The errors are also not significantly different
                    across the entire measurement duration.

        Args:
            cpm_reg (int): The L2-regularization value. Setting this argument to ``0`` removes
                        the regularization and is equivalent to performing ordinary least squares.
            rescale (Optional[boolean]): Choose whether to use zero-centered and median rescaled values
                        when performing least squares. The default is ``True`` and is recommended for numerical stability.
            polynomials (Optional[boolean]): Choose whether to include a set of polynomials (1, t, t^2, t^3)
                        as model components. The default is ``False``.
            updated_y (Optional[array]): Manually pass the target fluxes to use
            updated_m (Optionam[array]): Manually pass the design matrix to use 
        
        """
        if ((self.is_target_set  == False) or (self.is_exclusion_set == False)
           or (self.are_predictors_set == False)):
            print("You missed a step.")
        
        self.cpm_regularization = cpm_reg
        num_components = self.num_predictor_pixels
        self.rescale = rescale
        self.polynomials = polynomials
        l = None

        if (updated_y is None) & (updated_m is None):
            if (rescale == False):
                print("Calculating parameters using unscaled values.")
                y = self.target_fluxes
                m = self.predictor_pixels_fluxes  # Shape is (num of measurements, num of predictors)
                l = cpm_reg*np.identity(num_components)
            
            elif (rescale == True):
                y = self.rescaled_target_fluxes
                m = self.rescaled_predictor_pixels_fluxes
                l = cpm_reg*np.identity(num_components)

        else:
            # print("Values are being updated")
            y = updated_y
            m = updated_m

        # This is such a hack I need to fix this (August 2nd, 2019)
        if l is None:
            l = cpm_reg*np.identity(num_components)
    
        if (polynomials == True):
            if (updated_m is None):
                m = np.hstack((m, self.v_matrix))
            # print("Final Design Matrix Shape: {}".format(m.shape))
            num_components = num_components + self.v_matrix.shape[1]
            l = np.hstack((np.repeat(cpm_reg, self.num_predictor_pixels),
                            np.repeat(self.poly_reg, self.poly_terms)))*np.identity(num_components)



        if (self.trained == False):  # if it's the first time being called, store the original design matrix
            self.orig_m = m
        self.m = m
            
        # l = reg*np.identity(num_components)
        a = np.dot(m.T, m) + l
        b = np.dot(m.T, y)
        
        self.lsq_params = np.linalg.solve(a, b)
        # self.lsq_prediction = np.dot(m, self.lsq_params)

        self.lsq_prediction = np.dot(self.orig_m, self.lsq_params)

        self.cpm_params = self.lsq_params[:self.num_predictor_pixels]
        self.poly_params = self.lsq_params[self.num_predictor_pixels:]

        # print("poly_params", self.poly_params)

        self.const_prediction = None
        self.cpm_prediction = None
        self.poly_prediction = None

        if (polynomials == True):
            self.const_prediction = self.poly_params[0]  # Constant offset
            # self.cpm_prediction = np.dot(m[:, :self.num_predictor_pixels], self.cpm_params)
            # self.poly_prediction = np.dot(m[:, self.num_predictor_pixels:], self.poly_params) - self.const_prediction

            self.cpm_prediction = np.dot(self.orig_m[:, :self.num_predictor_pixels], self.cpm_params)
            self.poly_prediction = np.dot(self.orig_m[:, self.num_predictor_pixels:], self.poly_params) - self.const_prediction
        
        # if (rescale == True):
        #     self.lsq_prediction = np.median(self.target_fluxes)*(self.lsq_prediction + 1)
        #     if (polynomials == True):
        #         self.constant_prediction = np.median(self.target_fluxes)*self.poly_params[0]
        #         self.cpm_prediction = np.median(self.target_fluxes)*(self.cpm_prediction + 1)
        #         self.poly_prediction = np.median(self.target_fluxes)*(self.poly_prediction + 1) - self.constant_prediction
                
        self.trained = True

    def get_contributing_pixels(self, number):
        """Return the n-most contributing pixels' locations and a mask to see them"""
        if self.trained == False:
            print("You need to train the model first.")
            
        if self.fit == None:
            idx = np.argsort(np.abs(self.cpm_params))[:-(number+1):-1]
        else:
            idx = np.argsort(np.abs(self.fit.x))[:-(number+1):-1]
        
        top_n_loc = self.predictor_pixels_locations[idx]
        loc = top_n_loc.T
        top_n = np.zeros(self.im_fluxes[0].shape)
        top_n[loc[0], loc[1]] = 1
        
        top_n_mask = np.ma.masked_where(top_n == 0, top_n)
        
        return (top_n_loc, top_n_mask)

    def _batch(self, cpm_reg, rows, cols, exclusion=4, exclusion_method="closest", num_predictor_pixels=256,
                        predictor_method="similar_brightness", rescale=True, polynomials=False):
        self.cpm_regularization = cpm_reg
        self.im_predicted_fluxes = np.empty(self.im_fluxes.shape)
        for (row, col) in zip(rows, cols):
            self.set_target(row, col)
            self.set_exclusion(exclusion, method=exclusion_method)
            self.set_predictor_pixels(num_predictor_pixels, method=predictor_method)
            self.lsq(cpm_reg, rescale=rescale, polynomials=polynomials)
            if (polynomials == True):
                    self.im_predicted_fluxes[:, row, col] = self.cpm_prediction + self.const_prediction
            elif (polynomials == False):
                    self.im_predicted_fluxes[:, row, col] = self.lsq_prediction
        self.im_diff = self.rescaled_im_fluxes - self.im_predicted_fluxes

    def entire_image(self, cpm_reg, exclusion=4, exclusion_method="closest", num_predictor_pixels=256,
                        predictor_method="similar_brightness", rescale=True, polynomials=False):
        num_col = self.im_fluxes[0].shape[1]
        idx = np.arange(num_col**2)
        rows = idx // num_col
        cols = idx % num_col

        self._batch(cpm_reg, rows, cols, exclusion=exclusion, exclusion_method=exclusion_method, num_predictor_pixels=num_predictor_pixels,
                        predictor_method=predictor_method, rescale=rescale, polynomials=polynomials)

        self.over_entire_image = True

    def difference_image_sap(self, cpm_reg, row, col, size, exclusion=10, exclusion_method="closest", num_predictor_pixels=256,
                        predictor_method="similar_brightness", rescale=True, polynomials=True):
        """Simple Aperture Photometry for a given pixel in the difference images
        
        """

        if (self.over_entire_image == False):
            side = 2*size+1

            rows = np.repeat(np.arange(row-size, row+size+1), side)
            cols = np.tile(np.arange(col-size, col+size+1), side)

            self._batch(cpm_reg, rows, cols, exclusion=exclusion, exclusion_method=exclusion_method, num_predictor_pixels=num_predictor_pixels,
                        predictor_method=predictor_method, rescale=rescale, polynomials=polynomials)

        aperture = self.im_diff[:, max(0, row-size):min(row+size+1, self.im_diff.shape[1]), 
                            max(0, col-size):min(col+size+1, self.im_diff.shape[1])]
        aperture_lc = np.sum(aperture, axis=(1, 2))
        return aperture, aperture_lc

    def sigma_clip_process(self, sigma=5, subtract_polynomials=False):
        
        valid = np.full(self.time.shape[0], True)
        total_clipped_counter = 0
        prev_clipped_counter = 0
        iter_num = 1
        while True:
            if ((subtract_polynomials==False) & (self.cpm_prediction is not None)):
                model = self.cpm_prediction + self.const_prediction
            else:
                model = self.lsq_prediction 

            # if subtract_polynomials == True:
            #     model = self.lsq_prediction
            # else:

            #     model = self.cpm_prediction + self.const_prediction
            diff = self.rescaled_target_fluxes - model
            # print(np.sum(valid))
            # print(diff[valid].shape[0])
            sigma_boundary = sigma*np.sqrt(np.sum(np.abs(diff[valid])**2) / np.sum(valid))
            # print(sigma_boundary)
            valid[np.abs(diff) > sigma_boundary] = False
            total_clipped_counter = np.sum(~valid)
            cur_clipped_counter = total_clipped_counter - prev_clipped_counter
            if (cur_clipped_counter == 0):
                break
            print("Iteration {}: Removing {} data points".format(iter_num, cur_clipped_counter))
            prev_clipped_counter += cur_clipped_counter
            iter_num += 1
            self.valid = valid
            # pre_par = self.lsq_params
            self._rerun()
            # post_par = self.lsq_params
            # print("This better be false: {}".format(np.all(pre_par == post_par)))
            


            # time_m = np.ma.array(time_m, mask=clipped_mask)
            # # print("time_m length: {}".format(time_m.shape[0]))
            # diff_m = np.ma.array(diff_m, mask=clipped_mask)
            # # print("diff_m length: {}".format(diff_m.shape[0]))


    # def sigma_clip(self, sigma=3, iterations=3, subtract_polynomials=False):
    #     if subtract_polynomials == True:
    #         model = self.lsq_prediction
    #     else:
    #         model = self.cpm_prediction + self.const_prediction

    #     clipped_mask = np.zeros(self.time.shape[0])
    #     time_m = np.ma.array(self.time, mask=clipped_mask)
    #     diff = self.rescaled_target_fluxes - model
    #     diff_m = np.ma.array(diff, mask=clipped_mask)
    #     for i in range(iterations):
    #         sigma_boundary = sigma*np.sqrt(np.sum(np.abs(diff_m)**2) / np.count_nonzero(clipped_mask==0))
    #         # print(sigma_boundary)
    #         clipped_mask = np.abs(diff_m) > sigma_boundary  # clipped points
    #         print("Iteration {}: Removing {} data points".format(i+1, np.sum(clipped_mask)))
    #         time_m = np.ma.array(time_m, mask=clipped_mask)
    #         # print("time_m length: {}".format(time_m.shape[0]))
    #         diff_m = np.ma.array(diff_m, mask=clipped_mask)
    #         # print("diff_m length: {}".format(diff_m.shape[0]))
        
    #     self.clipped = clipped_mask
    #     # clipped_time = self.time[~self.clipped]
    #     # clipped_im_fluxes = self.im_fluxes[~self.clipped]
    #     # clipped_im_errors = self.im_errors[~self.clipped]

    #     # self._set_current_data(clipped_time, clipped_im_fluxes, clipped_im_errors)
    #     self._rerun()
    #         # self.sigma_clipped_time = self.time[~self.clipped]
    #         # self.sigma_clipped_fluxes = diff[~self.clipped]
    #     # self._update()
    #         # summary_plot(self, 20, subtract_polynomials=False)

    #     # self.clipped = clipped_mask
        
    def _rerun(self):
        # self.set_poly_model(self.time_interval, self.poly_terms, self.poly_reg)
        updated_y = self.rescaled_target_fluxes[self.valid]
        # print("updated_y shape: {}".format(updated_y.shape))
        updated_m = self.orig_m[self.valid, :]
        # print("updated_m shape: {}".format(updated_m.shape))
        # self.set_target_exclusion_predictors(self.target_row, self.target_col)
        self.lsq(self.cpm_regularization, self.rescale, self.polynomials, updated_y, updated_m)

    def _reset(self):
        self.__init__(self.file_path)

        

