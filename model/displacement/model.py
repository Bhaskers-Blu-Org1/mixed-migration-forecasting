"""
Trainer class to train all models.

For each country, we build a model for each year that we forecast.

"""

import joblib
import numpy as np
import pandas as pd
import logging
import os
import json
from time import time
from itertools import product
from functools import lru_cache

from sklearn.base import clone

from . import *
from .features import Generator
from .scenarios import Scenario

logger = logging.getLogger(__name__)


class Trainer(object):

    def __init__(self, config):
        """ Needs a configuration object and base year """

        self.config = config
        self.baseyear = config['BASEYEAR']
        self.generator = Generator(config, self.baseyear)
        self.scenarios = Scenario(self.generator.data, config)

        # get the grid search parameter results
        gs_params = json.load(open('params.json', 'rt'))
        self.parameters = {}
        for k in gs_params:
            self.parameters[(k['country'], k['lag'])] = k['params']

    def get_parameters(self, country, lag):
        """ Returns grid search parameters from look up """

        key = country, lag
        if key in self.parameters.keys():
            return self.parameters[key]

        else:
            logger.debug("Using default model parameters ({}, {}).".format(country, lag))
            return {"Estimator__loss": "ls", 
                "Estimator__n_estimators": 500, 
                "Estimator__learning_rate": 0.01, 
                "Estimator__max_depth": 5}


    @lru_cache(maxsize=1024)
    def score(self, countries=COUNTRIES, scenario=None):
        """
        Scoring loop to generate forecasts
        countries: List or a string 
        scenario: a tuple of tuple (an immutable represention of a Dict so it can be cached)
        """
        
        if scenario:
            scenario = {k: v for (k, v) in scenario}

        if not hasattr(self, 'models'):
            logger.warning("Models have not been trained. Training.")
            self.train()

        if isinstance(countries, str):
            countries = [countries]

        result = []

        for c in countries:

            F = self.generator.features(c, self.baseyear)
            _, _, Xv = F['data']

            D = self.generator.features(c, self.baseyear, differencing=True)
            _, _, Xdv = D['data']
            curr_for = D['baseline']

            if scenario:
                # get the total scenario change
                deltaT = self.scenarios.compute_target_change(Xv, scenario, c)
                MC = {'country': c, 
                      'explanation': deltaT[(c, 0)]['significance']}

            # TODO: Add non-scenario model explanation statements.
            MC = {'country': c,
                 'explanation': "Here is a test explanation clause that will be updated."}
            
            pred = []

            for lg in LAGS:
                
                key = (c, lg)
                
                bm = self.models[key]['base']
                cm = self.models[key]['change']

                fb = bm.predict(Xv)[0]

                # changes model predicts change in displacement.
                # for subsequent lag, update the displacement
                fc = cm.predict(Xdv)[0] + curr_for
                curr_for = fc

                # ensemble
                forecast = 0.5 * (fb + fc)

                if scenario:
                    # We assume year2 impacts persist across future years
                    sclag = max(SCENARIO_LAGS) if lg > max(SCENARIO_LAGS) else lg
                    forecast += deltaT[(c, sclag)]['change']

                logger.info("Forecasts {} (lag {}): base: {} change: {} ensemble:{}".format(c, lg, fb, fc, forecast))

                # Centre the range around the forecast
                ci_range = CI_LOOKUP[key]['upper'] - CI_LOOKUP[key]['lower']
                di = ci_range / 2.0

                M = {'year' :self.baseyear + lg, 
                     'forecast' : forecast, 
                     'scenario': scenario,
                     'CI_low':  forecast - di, 
                     'CI_high': forecast + di}
                
                pred.append(M)

            MC['prediction'] = pred
            MC['status'] = 'OK'
            result.append(MC)

        return result

    
    def train(self):
        """ Main training loop """

        logger.info("Training {} models for {} countries.".format(
            2 * len(LAGS), len(COUNTRIES)))

        start_time = time()
        self.models = {}

        for c, lg in product(COUNTRIES, LAGS):

            M = {'country': c, 'lag': lg, 'baseyear': self.baseyear}

            # Get training data for the base model
            F = self.generator.features(
                c, self.baseyear + lg, method='training')

            D = self.generator.features(
                c, self.baseyear + lg, method='training', differencing=True)

            Xt, yt, _ = F['data']

            base_model = clone(CLF)
            base_model.set_params(self.get_parameters(c, lg))

            base_model.fit(Xt, yt)
            M['base'] = base_model

            Xdt, ydt, _ = D['data']
            change_model = clone(CLF)
            change_model.fit(Xdt, ydt)
            M['change'] = change_model
            M['baseline'] = D['baseline']

            self.models[(c, lg)] = M

        logger.info("Done with {} models in {:3.2f} sec."
                    .format(len(LAGS) * len(COUNTRIES), time() - start_time))

    def load(self):
        """ load persisted models """

        if hasattr(self, 'models'):
            logger.info("Trained models replaced by persisted models.")
        
        try:
            self.models = joblib.load(self.config['MODELFILE']['displacement'])
        except FileNotFoundError:
            logger.error("Persisted models at {} not found".format(self.config['MODELFILE']['displacement']))


    def persist(self):
        """ store models to file """

        if not hasattr(self, 'models'):
            logger.info("Models hasn't been trained. Retraining.")
            self.train()

        joblib.dump(self.models, self.config['MODELFILE']['displacement'])
