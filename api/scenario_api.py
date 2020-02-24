from flask import Flask, render_template, jsonify, request, redirect, url_for, session
import json

from model.displacement import LABELS

def set_up(app, config):

    with open(config['GROUPING'], 'rt') as infile:
        groupings = json.load(infile)

    # User-facing labels recognized by model for scenario building
    groupings['labels'] = LABELS
    
    @app.route("/scenarios")
    def groups(): # pylint: disable=W0612
        return jsonify(groupings), 200
