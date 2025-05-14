#!/usr/bin/env python3

import logging
import os, sys, datetime, pprint
import re
from contextlib import suppress
# import time, uuid
import secrets
import requests
import yaml, json
import textwrap
import pickle
from copy import deepcopy

# Configure logging
# logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)


class InfluxdbHelper:
    #DASHBOARD_TEMPLATE_FILE = 'templates/dashboard-tpl.json'
    DASHBOARD_TEMPLATE_FILE = 'templates/dashboard-tpl.yaml'
    CHART_TEMPLATE_FILE = 'templates/charts-tpl.yaml'
    TEMPLATE_EXCLUDED_FIELDS = ['headers', 'user_password']

    def __init__(self, influxdb_base_url, admin_token, org_name, app_id):
        self.influxdb_base_url = influxdb_base_url
        self.set_headers(admin_token)

        app_id = self._normalize(app_id)

        self.org_name = org_name
        self.app_id = app_id
        self.bucket_name = self.name_of("bucket", app_id)    # Name for the new bucket
        self.retention = 3600                                     # 1 hour retention
        self.scraper_name = self.name_of("scraper", app_id)  # Name for the new scraper
        self.scraper_url = f"http://localhost:8086/metrics"       # URL for the new scraper
        self.user_name = self.name_of("user", app_id)        # Name for the new user
        self.user_password = self.create_password(app_id)         # Password for the new user
        self.var_name_metrics = self.name_of("var_metrics_list", app_id)  # Variable for listing/selecting a metric
        self.var_name_fields  = self.name_of("var_fields_list", app_id)   # Variable for listing/selecting a field
        self.dashboard_name = self.dashboard_name_of(app_id)      # Dashboard name

    # Naming functions
    def name_of(self, what, app_id):
        return f"neb_{app_id}_{what}"

    def dashboard_name_of(self, app_id):
        return f"Nebulous Dashboard {app_id}"

    def create_password(self, app_id):
        password_length = 32
        return secrets.token_urlsafe(password_length)

    def _normalize(self, app_id):
        app_id_norm = re.sub(r'[^A-Za-z0-9_]', r'_', app_id.strip())
        self.debug(f'normalize: {app_id} -> {app_id_norm}')
        return app_id_norm


# Header for authentication
    def set_headers(self, admin_token):
        self.headers = {
            "Authorization": f"Token {admin_token}",
            "Content-Type": "application/json"
        }

    def __pretty_print(self):
        pp = pprint.PrettyPrinter(indent=4, width=80)
        pp.pprint(vars(self))

    @staticmethod
    def debug(message):
        # m = f"\033[34m{message}\033[0m"
        m = message
        logger.debug(m)
        # print(m)

    @staticmethod
    def info(message):
        # m = f"\033[32m{message}\033[0m"
        m = message
        logger.info(m)
        # print(m)

    @staticmethod
    def warning(message):
        m = f"\033[33m{message}\033[0m"
        logger.warning(m)
        # print(m, file=sys.stderr)

    @staticmethod
    def error(message):
        m = f"\033[31m{message}\033[0m"
        logger.error(m)
        # print(m, file=sys.stderr)
        raise Exception(message)


    # 1. Set organization id from org. name
    def set_org(self):
        self._set_org(self.org_name)

    def _set_org(self, org_name):
        url = f"{self.influxdb_base_url}/api/v2/orgs"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            orgs = response.json()['orgs']
            for org in orgs:
                if org['name'] == org_name:
                    self.info(f"Organization '{org_name}' found with ID: {org['id']}")
                    self.org_id = org['id']
                    self.org_name = org_name
                    return org['id']
            self.error(f"Organization '{org_name}' not found")
        else:
            self.error(f"Error while fetching organization list: {response.text}")
        return None

    # 2. Create a new bucket
    def create_bucket(self):
        self.bucket_id = self._create_bucket(self.bucket_name, self.org_id)
        return self.bucket_id

    def _create_bucket(self, bucket_name, org_id):
        url = f"{self.influxdb_base_url}/api/v2/buckets"
        payload = {
            "orgID": org_id,
            "name": bucket_name,
            "retentionRules": [{"type": "expire", "everySeconds": self.retention}],
            "shardGroupDuration": "1h"
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"Bucket '{bucket_name}' created successfully!")
            self.debug(f"Response: {response.json()}")
            return response.json()['id']
        else:
            self.error(f"Error creating bucket: {response.text}")

    def delete_bucket(self):
        self._delete_bucket(self.bucket_id, self.bucket_name)

    def _delete_bucket(self, bucket_id, bucket_name):
        url = f"{self.influxdb_base_url}/api/v2/buckets/{bucket_id}"
        self.debug(f"Deleting bucket {bucket_name}: '{url}'")
        response = requests.delete(url, headers=self.headers)
        self.debug(f"Deleting bucket: RESPONSE: '{response}'")
        if response.status_code == 204:
            self.info(f"Bucket '{bucket_name}' deleted successfully!")
        else:
            self.error(f"Error deleting bucket: {response.text}")

    # 3. Create a new scraper
    def create_scraper(self):
        self.scraper_id = self._create_scraper(self.scraper_name, self.scraper_url, self.org_id, self.bucket_id)
        return self.scraper_id

    def _create_scraper(self, scraper_name, scraper_url, org_id, bucket_id):
        url = f"{self.influxdb_base_url}/api/v2/scrapers"
        payload = {
            "name": scraper_name,
            "orgID": org_id,
            "bucketID": bucket_id,
            "url": scraper_url
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"Scraper '{scraper_name}' created successfully!")
            self.debug(f"Response: {response.json()}")
            return response.json()['id']
        else:
            self.error(f"Error creating scrapper: {response.text}")

    def delete_scraper(self):
        self._delete_scraper(self.scraper_id, self.scraper_name)

    def _delete_scraper(self, scraper_id, scraper_name):
        url = f"{self.influxdb_base_url}/api/v2/scrapers/{scraper_id}"
        self.debug(f"Deleting scraper {scraper_name}: '{url}'")
        response = requests.delete(url, headers=self.headers)
        self.debug(f"Deleting scraper: RESPONSE: '{response}'")
        if response.status_code == 204:
            self.info(f"Scraper '{scraper_name}' deleted successfully!")
        else:
            self.error(f"Error deleting scrapper: {response.text}")

    # 4. Create a new user
    def create_user(self):
        self.user_id = self._create_user(self.user_name, self.user_password, self.org_id)
        self._update_user_password(self.user_id, self.user_name, self.user_password)
        return self.user_id

    def _create_user(self, user_name, user_password, org_id):
        url = f"{self.influxdb_base_url}/api/v2/users"
        payload = {
            "name": user_name,
            "password": user_password,
            "orgID": org_id
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"User '{user_name}' created successfully!")
            self.info(f"User password: {user_password}")
            return response.json()['id']
        else:
            self.error(f"Error creating user: {response.text}")

    def _update_user_password(self, user_id, user_name, user_password):
        url = f"{self.influxdb_base_url}/api/v2/users/{user_id}/password"
        payload = {
            "password": user_password
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 204:
            self.info(f"User '{user_name}' password updated successfully!")
        else:
            self.error(f"Error updating user password: {response.text}")

    def delete_user(self):
        self._delete_user(self.user_id, self.user_name)

    def _delete_user(self, user_id, user_name):
        url = f"{self.influxdb_base_url}/api/v2/users/{user_id}"
        self.debug(f"Deleting user {user_name}: '{url}'")
        response = requests.delete(url, headers=self.headers)
        self.debug(f"Deleting user: RESPONSE: '{response}'")
        if response.status_code == 204:
            self.info(f"User '{user_name}' deleted successfully!")
        else:
            self.error(f"Error deleting user: {response.text}")

    # 5. Create a new variable
    def create_variables(self):
        self.var_id_metrics = self._create_variable(
                self.var_name_metrics,
                textwrap.dedent(f'''
                import "influxdata/influxdb/schema"
                schema.measurements(bucket: "{self.bucket_name}")'''),
                self.org_id)
        self.var_id_fields = self._create_variable(
                self.var_name_fields,
                textwrap.dedent(f'''
                import "influxdata/influxdb/schema"
                schema.fieldKeys(
                  bucket: "{self.bucket_name}",
                  predicate: (r) => r._measurement == v.{self.var_name_metrics}
                                    and r._field !~ /^(\\d.*)/
                                    and r._field !~ /^(?i)(\\+inf|-inf)$/
                )'''),
                self.org_id)
        return self.var_id_metrics, self.var_id_fields

    def _create_variable(self, variable_name, variable_query, org_id):
        url = f"{self.influxdb_base_url}/api/v2/variables"
        payload = {
            "arguments": {
                "type": "query",
                "values": {
                    "language": "flux",
                    "query": variable_query
                }
            },
            "name": variable_name,
            "orgID": org_id
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"Variable '{variable_name}' created successfully!")
            self.debug(f"Response: {response.json()}")
            return response.json()['id']
        else:
            self.error(f"Error creating variable: {response.text}")

    def delete_variables(self):
        self._delete_variable(self.var_id_metrics, self.var_name_metrics)
        self._delete_variable(self.var_id_fields, self.var_name_fields)

    def _delete_variable(self, variable_id, variable_name):
        url = f"{self.influxdb_base_url}/api/v2/variables/{variable_id}"
        self.debug(f"Deleting variable {variable_name}: '{url}'")
        response = requests.delete(url, headers=self.headers)
        self.debug(f"Deleting dashboard: RESPONSE: '{response}'")
        if response.status_code == 204:
            self.info(f"Variable '{variable_name}' deleted successfully!")
        else:
            self.error(f"Error deleting variable: {response.text}")

    # 6. Create a new dashboard from template
    def create_dashboard(self):
        dashboard_data, dashboard_tpl = self._create_dashboard(self.dashboard_name, self.org_id)
        self.dashboard_id = dashboard_data['id']
        self._create_cell_views(dashboard_data, dashboard_tpl)
        return self.dashboard_id

    def _create_dashboard(self, dashboard_name, org_id):
        url = f"{self.influxdb_base_url}/api/v2/dashboards"
        payload = self._load_dashboard_template(self.DASHBOARD_TEMPLATE_FILE)
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"Dashboard '{dashboard_name}' created successfully!")
            self.debug(f"Response: {response.json()}")
            return response.json(), payload
        else:
            self.error(f"Error creating dashboard: {response.text}")

    def _load_dashboard_template(self, file_path):
        # with open(file_path) as f: input_string = f.read()
        with open(file_path, 'r') as file:
            input_string = file.read()
            #for placeholder, replacement in placeholders.items():
            #    input_string = input_string.replace(f'{{{placeholder}}}', str(replacement))
            for field, value in self.__dict__.items():
                if field in self.TEMPLATE_EXCLUDED_FIELDS:
                    continue
                else:
                    self.debug(f".........{field} = {value}")
                    input_string = input_string.replace(f'{{{field}}}', str(value))

            data = yaml.safe_load(input_string)
            json_string = json.dumps(data, indent=2)
            json_data = json.loads(json_string)
            self.debug(f"_load_dashboard_template result: {json_data}")
            return json_data

    def _create_cell_views(self, dashboard_data, dashboard_tpl):
        dashboard_id = dashboard_data['id']
        templates = self._load_dashboard_template(self.CHART_TEMPLATE_FILE)
        for c in dashboard_data['cells']:
            url = f"{self.influxdb_base_url}/api/v2/dashboards/{dashboard_id}/cells/{c["id"]}/view"
            cell_tpl = next((x for x in dashboard_tpl['cells'] if x['name'] == c['name']), None)
            cell_template = cell_tpl["cell-template"] or "default_chart"
            payload = deepcopy( templates[cell_template] )
            payload["name"] = c["name"] or "Unnamed cell"
            response = requests.patch(url, headers=self.headers, json=payload)
            if response.status_code == 200:
                self.info(f"      Cell '{c["name"]}' patched successfully!")
            else:
                self.error(f"Error patching cell: {response.text}")

    def delete_dashboard(self):
        self._delete_dashboard(self.dashboard_id, self.dashboard_name)

    def _delete_dashboard(self, dashboard_id, dashboard_name):
        url = f"{self.influxdb_base_url}/api/v2/dashboards/{dashboard_id}"
        self.debug(f"Deleting dashboard {dashboard_name} : {url}")
        response = requests.delete(url, headers=self.headers)
        self.debug(f"Deleting dashboard: RESPONSE: '{response}'")
        if response.status_code == 204:
            self.info(f"Dashboard '{dashboard_name}' successfully deleted!")
        else:
            self.error(f"Error deleting dashboard {dashboard_name} : {response.text}")

    # 7. Grant all privileges to the user
    def grant_privileges(self):
        self._grant_privileges(self.user_id, self.user_name, self.dashboard_id, self.bucket_id, self.org_id)

    def _grant_privileges(self, user_id, user_name, dashboard_id, bucket_id, org_id):
        url = f"{self.influxdb_base_url}/api/v2/authorizations"
        payload = {
            "orgID": org_id,
            "userID": user_id,
            "status": "active",
            "description": f"{user_name}'s token",
            "permissions": [
                {"action": "read", "resource": {"type": "buckets", "id": bucket_id}},
                {"action": "write", "resource": {"type": "buckets", "id": bucket_id}},
                {"action": "read", "resource": {"type": "dashboards", "id": dashboard_id}},
                {"action": "write", "resource": {"type": "dashboards", "id": dashboard_id}}
            ]
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            self.info(f"Granted all privileges to user '{self.user_name}'!")
        else:
            self.error(f"Error granting privileges: {response.text}")

    def revoke_privileges(self):
        self._revoke_privileges(self.user_id)

    def _revoke_privileges(self, user_id):
        # Get user authorizations
        authorizations = self._get_user_authorizations(user_id)

        # Delete each user authorization
        for auth in authorizations:
            url = f"{self.influxdb_base_url}/api/v2/authorizations/{auth['id']}"
            self.debug(f'Deleting user authorization: {url}')
            response = requests.delete(url, headers=self.headers)
            self.debug(f"Deleting user authorization: RESPONSE: '{response}'")
            if response.status_code == 204:
                self.debug(f"Deleted user authorization: '{auth['id']}'")
            else:
                self.error(f"Error deleting authorization : {response.text}")
        self.info(f"Deleted user authorizations: '{self.user_name}'")

    # Functions for getting Authorizations
    def _get_all_authorizations(self):
        # Get all authorizations
        url = f"{self.influxdb_base_url}/api/v2/authorizations"
        self.debug(f"Getting all authorizations: '{url}'")
        response = requests.get(url, headers=self.headers)
        self.debug(f"Getting all authorizations: RESPONSE: '{response}'")
        if response.status_code == 200:
            self.debug(f"Got all authorizations!")
            self.debug(response.json())
            return response.json()['authorizations']
        else:
            self.error(f"Error retrieving authorizations: {response.text}")
            return None

    def _get_user_authorizations(self, user_id):
        # Get all authorizations
        authorizations = self._get_all_authorizations()

        # Extract this user's authorizations
        self.debug(f"All authorizations: {authorizations}")
        authorizations = [x for x in authorizations if x['userID'] == user_id]
        self.debug(f"User authorizations: {authorizations}")

        return authorizations


    # Function to run all tasks
    def create_all(self):
        self.set_org()          # Step 1: Set Org. Id
        self.create_bucket()    # Step 2: Create bucket
        self.create_scraper()   # Step 3: Create scraper for writing data to bucket
        self.create_user()      # Step 4: Create user
        self.create_variables() # Step 5: Create variables
        self.create_dashboard() # Step 6: Create dashboard with a graph cell
        self.grant_privileges() # Step 7: Grant privileges to user

    # Function to delete all resources
    def delete_all(self):
        with suppress(Exception): self.revoke_privileges() # Step 7: Revoke privileges from user
        with suppress(Exception): self.delete_dashboard()  # Step 6: Delete dashboard with a graph cell
        with suppress(Exception): self.delete_variables()  # Step 5: Delete variables
        with suppress(Exception): self.delete_user()       # Step 4: Delete user
        with suppress(Exception): self.delete_scraper()    # Step 3: Delete scraper for writing data to bucket
        with suppress(Exception): self.delete_bucket()     # Step 2: Delete bucket

    # Function for finding all related info (id's, names) for an App.Id
    def find_all(self, app_id):
        app_id = self._normalize(app_id)
        self.set_org()
        self.bucket_id, self.bucket_name = self._query("buckets", f"/api/v2/buckets?orgID={self.org_id}", 'buckets', self.name_of("bucket", app_id))
        self.scraper_id, self.scraper_name = self._query("scrapers", "/api/v2/scrapers", 'configurations', self.name_of("scraper", app_id))
        self.user_id, self.user_name = self._query("users", "/api/v2/users", 'users', self.name_of("user", app_id))
        self.var_id_metrics, self.var_name_metrics = self._query("variables", "/api/v2/variables", 'variables', self.name_of("var_metrics_list", app_id))
        self.var_id_fields, self.var_name_fields = self._query("variables", "/api/v2/variables", 'variables', self.name_of("var_fields_list", app_id))
        self.dashboard_id, self.dashboard_name = self._query("dashboards", "/api/v2/dashboards", 'dashboards', self.dashboard_name_of(app_id))
        self.info(f"    Found bucket:    {self.bucket_id}  {self.bucket_name}")
        self.info(f"    Found scraper:   {self.scraper_id}  {self.scraper_name}")
        self.info(f"    Found user:      {self.user_id}  {self.user_name}")
        self.info(f"    Found var. metrics list: {self.var_id_metrics}  {self.var_name_metrics}")
        self.info(f"    Found var. fields list:  {self.var_id_fields}  {self.var_name_fields}")
        self.info(f"    Found dashboard: {self.dashboard_id}  {self.dashboard_name}")

    def _query(self, what, url_path, json_section, search):
        url = f"{self.influxdb_base_url}{url_path}"
        self.debug(f"Getting all {what}: '{url}'")
        response = requests.get(url, headers=self.headers)
        self.debug(f"Getting all {what}: RESPONSE: '{response}'")
        if response.status_code == 200:
            self.debug(f"Got all {what}!")
            self.debug(response.json())
            self.debug(f'JSON section to use: {json_section}')
            self.debug(f'Searching for: {search}')
            if response.json() and response.json()[json_section]:
                for x in response.json()[json_section]:
                    self.debug(f' --- Checking: {x}')
                    if x['name'] and search in x['name']:
                        self.debug(f' --- Found {search} : {x}')
                        return x['id'], x['name']
            self.error(f'ERROR: Not found {search} in {json_section}')
            return None, None
        else:
            self.error(f"Error retrieving {what}: {response.text}")

    # Debug print all variable values
    def print(self):
        for field, value in self.__dict__.items():
            self.debug(f"-- {field} := {value}")
        # print(vars(self))

    def saveToFile(self, file_name):
        os.makedirs(os.path.dirname(file_name), exist_ok=True)
        with open(file_name, 'w') as outfile:
            yaml.dump(self.__dict__, outfile, default_flow_style=False)

    def loadFromFile(self, file_name):
        with open(file_name, 'r') as infile:
            dataMap = yaml.safe_load(infile)
            for field, value in dataMap.items():
                setattr(self, field, value)

    # Save Helper state to a file
    def serialize(self, file_name):
        # Serialize to a file
        with open(file_name, "wb") as file:
            pickle.dump(self, file)

    @staticmethod
    def deserialize(file_name):
        # Deserialize the object
        with open(file_name, "rb") as file:
            obj = pickle.load(file)
        return obj

    # ----------------------------------------------------------------------

    # List users
    def list_users(self):
        url = f"{self.influxdb_base_url}/api/v2/users"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            users = response.json()['users']
            if users:
                self.info(f"Listing all users:")
                for user in users:
                    self.debug(user)
                    self.info(f"User: {user['name']}, ID: {user['id']}")
            else:
                self.info("No users found.")
        else:
            self.error(f"Error while fetching user list: {response.text}")

    # ----------------------------------------------------------------------


# Configuration: Replace with your InfluxDB instance details
# INFLUXDB_URL = os.environ.get('INFLUXDB_URL')  # InfluxDB instance URL
# ORG_NAME = os.environ.get('INFLUXDB_ORG_NAME')  # Organization name
# ADMIN_TOKEN = os.environ.get('INFLUXDB_ADMIN_TOKEN')  # Admin token for authentication

#APP_ID = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
# APP_ID = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
# print(f" APP_ID: {APP_ID}")
#METRIC_NAMES = [x.strip() for x in sys.argv[2].split(',')] if len(sys.argv) > 2 else []
#print(f"METRICS: {METRIC_NAMES}")
# sys.exit()

# Main function to run all tasks
if __name__ == "__main__":
    INFLUXDB_URL = os.environ.get('INFLUXDB_URL')  # InfluxDB instance URL
    ORG_NAME = os.environ.get('INFLUXDB_ORG_NAME')  # Organization name
    ADMIN_TOKEN = os.environ.get('INFLUXDB_ADMIN_TOKEN')  # Admin token for authentication

    APP_ID = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    # print(f" APP_ID: {APP_ID}")
    InfluxdbHelper.info(f" APP_ID: {APP_ID}")

    helper = InfluxdbHelper(INFLUXDB_URL, ADMIN_TOKEN, ORG_NAME, APP_ID)
    helper.create_all()

#     helper.serialize(f"{APP_ID}.pkl")
#     helper.list_users()
#     helper.print()

#     helper2 = InfluxdbHelper.deserialize(f"{APP_ID}.pkl")
#     helper2.delete_all()
