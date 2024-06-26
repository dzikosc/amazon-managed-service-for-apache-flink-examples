"""
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
"""

"""
main.py
~~~~~~~~~~~~~~~~~~~
This module:
    1. Creates the execution environment
    2. Sets any special configuration for local mode (e.g. when running in the IDE)
    3. Retrieves the runtime configuration
    4. Creates a source table to generate data using DataGen connector
    5. Creates a sink table to Amazon Data Firehose 
    6. Inserts into the sink table from the source table
"""

from pyflink.table import EnvironmentSettings, TableEnvironment
import os
import json
import logging
import pyflink

#######################################
# 1. Creates the execution environment
#######################################

env_settings = EnvironmentSettings.in_streaming_mode()
table_env = TableEnvironment.create(env_settings)

# Location of the configuration file when running on Managed Flink.
# NOTE: this is not the file included in the project, but a file generated by Managed Flink, based on the
# application configuration.
APPLICATION_PROPERTIES_FILE_PATH = "/etc/flink/application_properties.json"

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
        "file:///" + CURRENT_DIR + "/target/pyflink-dependencies.jar",
    )

    # Show the PyFlink home directory and the directory where logs will be written, when running locally
    print("PyFlink home: " + os.path.dirname(os.path.abspath(pyflink.__file__)))
    print("Logging directory: " + os.path.dirname(os.path.abspath(pyflink.__file__)) + '/log')


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
    #########################################
    # 3. Retrieves the runtime configuration
    #########################################

    props = get_application_properties()
    output_delivery_stream_name = property_map(props, "OutputDeliveryStream0")["stream.name"]
    output_delivery_stream_region = property_map(props, "OutputDeliveryStream0")["aws.region"]

    logging.info("Output Firehose delivery stream: {}, region: {}".format(output_delivery_stream_name,
                                                                          output_delivery_stream_region))

    #################################################
    # 4. Define input table using datagen connector
    #################################################

    # In a real application, this table will probably be connected to a source stream, using for example the 'kinesis'
    # connector.
    table_env.execute_sql("""
             CREATE TABLE sensor_readings (
                 sensor_id INT,
                 temperature DOUBLE,
                 measurement_time TIMESTAMP(3)
               )
               PARTITIONED BY (sensor_id)
               WITH (
                 'connector' = 'datagen',
                 'fields.sensor_id.min' = '10',
                 'fields.sensor_id.max' = '20',
                 'fields.temperature.min' = '0',
                 'fields.temperature.max' = '100'
               )
     """)

    ###################################################################################
    # 5. Creates a sink table to Amazon Data Firehose, using the 'firehose' connector
    ###################################################################################

    table_env.execute_sql(f"""
            CREATE TABLE output (
                sensor_id INT,
                temperature_f DOUBLE,
                measurement_time TIMESTAMP(3)
              )
              WITH (
                'connector' = 'firehose',
                'delivery-stream' = '{output_delivery_stream_name}',
                'aws.region' = '{output_delivery_stream_region}',
                'format' = 'json',
                'json.timestamp-format.standard' = 'ISO-8601'
              )
        """)

    # For local development purposes, you might want to print the output to the console, instead of sending it to a
    # Kinesis Stream. To do that, you can replace the sink table using the 'kinesis' connector, above, with a sink table
    # using the 'print' connector. Comment the statement immediately above and uncomment the one immediately below.

    # table_env.execute_sql("""
    #     CREATE TABLE output (
    #             sensor_id INT,
    #             temperature_f DOUBLE,
    #             measurement_time TIMESTAMP(3)
    #           )
    #           WITH (
    #             'connector' = 'print'
    #           )
    # """)

    # Executing an INSERT INTO statement will trigger the job
    table_result = table_env.execute_sql("""
            INSERT INTO output 
            SELECT sensor_id, temperature, measurement_time 
                FROM sensor_readings
    """)

    # When running locally, as a standalone Python application, you must instruct Python not to exit at the end of the
    # main() method, otherwise the job will stop immediately.
    # When running the job deployed in a Flink cluster or in Amazon Managed Service for Apache Flink, the main() method
    # must end once the flow has been defined and handed over to the Flink framework to run.
    if is_local:
        table_result.wait()


if __name__ == "__main__":
    main()
