from dbnd import PythonTask, parameter, pipeline, task


class TestDocRunningPipelines:
    def test_doc(self):
        #### DOC START

        @task
        def prepare_data(data: str) -> str:
            return data

        #### DOC END
        prepare_data.dbnd_run(data="Hello Databand!")
