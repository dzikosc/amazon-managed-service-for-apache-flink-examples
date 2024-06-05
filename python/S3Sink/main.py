'''
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

"""
main.py
~~~~~~~~~~~~~~~~~~~
This module:
    1. Creates the execution environment
    2. Sets any special configuration for local mode (e.g. when running in the IDE)
    3. Retrieves the runtime configuration
    4. Creates a source table to generate data using DataGen connector
    5. Creates a sink table writing to an S3 Bucket
    6. Inserts into the Sink table (S3)
"""

from pyflink.table import EnvironmentSettings, TableEnvironment
import pyflink
import os
import json
import logging

#######################################
# 1. Creates the execution environment
#######################################

env_settings = EnvironmentSettings.in_streaming_mode()
table_env = TableEnvironment.create(env_settings)

# Location of the configuration file when running on Managed Flink.
# NOTE: this is not the file included in the project, but a file generated by Managed Flink, based on the
# application configuration.
APPLICATION_PROPERTIES_FILE_PATH = "/etc/flink/application_properties.json"  # on kda

# Set the environment variable IS_LOCAL=true in your local development environment,
# or in the run profile of your IDE: the application relies on this variable to run in local mode (as a standalone
# Python application, as opposed to running in a Flink cluster).
# Differently from Java Flink, PyFlink cannot automatically detect when running in local mode
is_local = (
    True if os.environ.get("IS_LOCAL") else False
)

##############################################
# 2. Set special configuration for local mode
##############################################

if is_local:
    # only for local, overwrite variable to properties and pass in your jars delimited by a semicolon (;)
    APPLICATION_PROPERTIES_FILE_PATH = "application_properties.json"  # local

    CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
    table_env.get_config().get_configuration().set_string(
        "pipeline.jars",
        # For local development (only): use the fat-jar containing all dependencies, generated by `mvn package`
        # located in the target/ subdirectory
        "file:///" + CURRENT_DIR + "/target/pyflink-dependencies.jar"
    )

    # Show the PyFlink home directory and the directory where logs will be written, when running locally
    print("PyFlink home: " + os.path.dirname(os.path.abspath(pyflink.__file__)))
    print("Logging directory: " + os.path.dirname(os.path.abspath(pyflink.__file__)) + '/log')

    # Checkpointing must be enabled when using S3Sink. Part files are finalised on checkpoint.
    # When running on Amazon Managed Service for Apache Flink, checkpointing is controlled by the application
    # configuration (enabled by default).
    # When running locally, you need to enable checkpointing explicitly, or fill will stay forever in progress or
    # pending.
    table_env.get_config().get_configuration().set_string(
        "execution.checkpointing.mode", "EXACTLY_ONCE"
    )

    table_env.get_config().get_configuration().set_string(
        "execution.checkpointing.interval", "1 min"
    )


# Utility method, extracting properties from the runtime configuration file
def get_application_properties():
    if os.path.isfile(APPLICATION_PROPERTIES_FILE_PATH):
        with open(APPLICATION_PROPERTIES_FILE_PATH, "r") as file:
            contents = file.read()
            properties = json.loads(contents)
            return properties
    else:
        print('A file at "{}" was not found'.format(APPLICATION_PROPERTIES_FILE_PATH))


# Utility method, extracting a property from a property group
def property_map(props, property_group_id):
    for prop in props:
        if prop["PropertyGroupId"] == property_group_id:
            return prop["PropertyMap"]


def main():

    #####################################
    # 3. Retrieve runtime configuration
    #####################################

    props = get_application_properties()
    s3_bucket_name = property_map(props, "bucket")["name"]
    logging.info("Output bucket: {}".format(s3_bucket_name))

    #################################################
    # 4. Define input table using datagen connector
    #################################################

    # In a real application, this table will probably be connected to a source stream, using for example the 'kinesis'
    # connector.
    table_env.execute_sql("""CREATE TABLE sensor_readings (
                sensor_id INT,
                temperature NUMERIC(6,2),
                measurement_time TIMESTAMP(3)
              )
              PARTITIONED BY (sensor_id)
              WITH (
                'connector' = 'datagen',
                'fields.sensor_id.min' = '10',
                'fields.sensor_id.max' = '20',
                'fields.temperature.min' = '0',
                'fields.temperature.max' = '100'
              ) """)

    ##############################
    # 5. Define sink tables to S3
    ##############################

    table_env.execute_sql("""
            CREATE TABLE sensors_out (
                sensor_id INT NOT NULL,
                temperature NUMERIC(6,2) NOT NULL,
                `time` TIMESTAMP_LTZ(3) NOT NULL
            )
            PARTITIONED BY (sensor_id)
            WITH (
                  'connector'='filesystem',
                  'path'='s3a://{0}/pyflinkl-filesink-example-output/',
                  'format'='json',
                  'json.timestamp-format.standard' = 'ISO-8601',
                  'sink.partition-commit.policy.kind'='success-file',
                  'sink.partition-commit.delay' = '1 min'
            ) """.format(s3_bucket_name))

    #
    # table_env.execute_sql("""
    #         CREATE TABLE sensors_out (
    #             sensor_id INT NOT NULL,
    #             temperature NUMERIC(6,2) NOT NULL,
    #             `time` TIMESTAMP_LTZ(3) NOT NULL
    #         )
    #         PARTITIONED BY (sensor_id)
    #         WITH (
    #               'connector'='print'
    #         ) """)

    ################################
    # 6. Insert into the sink table
    ################################

    table_result = table_env.execute_sql("""
            INSERT INTO sensors_out 
            SELECT sensor_id, temperature, measurement_time as `time` 
            FROM sensor_readings""")

    # When running locally, as a standalone Python application, you must instruct Python not to exit at the end of the
    # main() method, otherwise the job will stop immediately.
    # When running the job deployed in a Flink cluster or in Amazon Managed Service for Apache Flink, the main() method
    # must end once the flow has been defined and handed over to the Flink framework to run.
    if is_local:
        table_result.wait()


if __name__ == "__main__":
    main()
